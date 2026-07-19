# modules/report_generator.py
import os
import csv
import shutil
from datetime import datetime
import pytz
import logging
import time
import threading

logger = logging.getLogger(__name__)

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False
    logger.warning("⚠️ openpyxl не установлен, отчеты будут в CSV формате")


class ReportGenerator:
    def __init__(self, file_manager, db):
        self.fm = file_manager
        self.db = db
        self.MAX_WAIT_TIME = 60  # Увеличено до 60 секунд
        self.CHECK_INTERVAL = 2  # Интервал проверки в секундах
        self._generating = {}  # Словарь для отслеживания активных генераций {user_id: timestamp}
        self._lock = threading.Lock()  # Блокировка для предотвращения множественных вызовов
    
    def generate_report(self, user_id, wait_for_links=True):
        """
        Генерирует Excel отчет с двумя листами.
        
        Args:
            user_id: ID пользователя
            wait_for_links: Ждать ли появления ссылок
        """
        # ЗАЩИТА ОТ МНОЖЕСТВЕННЫХ ВЫЗОВОВ
        with self._lock:
            if user_id in self._generating:
                elapsed = time.time() - self._generating[user_id]
                if elapsed < 120:  # Увеличено до 2 минут
                    logger.warning(f"⚠️ Генерация отчета для {user_id} уже выполняется (прошло {elapsed:.1f}с)")
                    return None
                else:
                    logger.warning(f"⚠️ Предыдущая генерация для {user_id} зависла, разрешаем новый вызов")
            
            self._generating[user_id] = time.time()
        
        try:
            user_folder = self.fm.get_user_folder(user_id)
            
            # Получаем все публикации
            publications = self.db.get_publications(user_id)
            
            if not publications:
                logger.warning(f"⚠️ Нет публикаций для пользователя {user_id}")
                with self._lock:
                    del self._generating[user_id]
                return None
            
            # Проверяем наличие pending публикаций
            pending_count = self.db.count_pending_publications(user_id)
            
            if pending_count > 0 and wait_for_links:
                logger.info(f"⏳ Обнаружено {pending_count} pending публикаций, ожидаем ссылки...")
                self._wait_for_links(user_id, publications)
                # Обновляем список после ожидания
                publications = self.db.get_publications(user_id)
                pending_count = self.db.count_pending_publications(user_id)
            
            # ФИЛЬТРУЕМ ТОЛЬКО УСПЕШНЫЕ ПУБЛИКАЦИИ
            success_publications = []
            error_publications = []
            
            for pub in publications:
                if pub.get('status') == 'success':
                    success_publications.append(pub)
                elif pub.get('status') != 'pending':
                    error_publications.append(pub)
            
            if not success_publications:
                logger.warning(f"⚠️ Нет успешных публикаций для пользователя {user_id}")
                if pending_count > 0:
                    logger.warning(f"⚠️ {pending_count} публикаций все еще в статусе 'pending'")
                with self._lock:
                    del self._generating[user_id]
                return None
            
            logger.info(f"📊 Найдено {len(success_publications)} успешных публикаций, {len(error_publications)} с ошибками")
            
            moscow_tz = pytz.timezone('Europe/Moscow')
            success_data = []
            error_data = []
            
            publications_sorted = sorted(success_publications, key=lambda x: x.get('created_at', ''))
            current_date = None
            index = 1
            
            for pub in publications_sorted:
                folder_name = pub.get('folder_name', '')
                chat_id = pub.get('group_id', '')
                
                # Получаем метаданные из БД
                metadata = self.db.get_ad_metadata(user_id, folder_name)
                
                # Читаем post_link из метаданных (теперь всегда есть словарь)
                post_link = metadata.get('post_link')
                
                # ЛОГИРУЕМ СТАТУС
                if post_link:
                    logger.info(f"🔗 Для папки {folder_name} post_link: '{post_link}'")
                else:
                    # Если публикация success, но ссылки нет - это аномалия
                    logger.warning(f"⚠️ Для папки {folder_name} post_link отсутствует, хотя статус 'success'")
                    # Пробуем обновить статус на 'pending' чтобы система дождалась ссылки
                    self.db.update_publication_status(user_id, folder_name, 'pending', 
                                                     error="Ссылка не найдена, повторное ожидание")
                    continue  # Пропускаем эту публикацию в отчете
                
                # Время публикации
                created_at = pub.get('created_at')
                if created_at:
                    if isinstance(created_at, str):
                        try:
                            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        except:
                            created_at = datetime.now(moscow_tz)
                    
                    if hasattr(created_at, 'tzinfo') and created_at.tzinfo is None:
                        created_at = moscow_tz.localize(created_at)
                    elif hasattr(created_at, 'tzinfo'):
                        created_at = created_at.astimezone(moscow_tz)
                    
                    date_str = created_at.strftime('%d.%m.%Y')
                    time_str = created_at.strftime('%H.%M')
                else:
                    now = datetime.now(moscow_tz)
                    date_str = now.strftime('%d.%m.%Y')
                    time_str = now.strftime('%H.%M')
                
                if current_date != date_str:
                    current_date = date_str
                    display_date = date_str
                else:
                    display_date = ''
                
                success_data.append({
                    '№': index,
                    'Дата': display_date,
                    'Время публикации (МСК)': time_str,
                    'Ссылка на пост': post_link if post_link else '⚠️ Ссылка не получена',
                    'Ссылка (источник)': metadata.get('Ссылка', ''),
                    'Название': metadata.get('Название', ''),
                    'Код предложения': metadata.get('Код предложения', ''),
                    'Цена в лизинге': metadata.get('Цена в лизинге', ''),
                })
                index += 1
            
            # Добавляем ошибки в отчет
            for pub in error_publications:
                folder_name = pub.get('folder_name', '')
                error = pub.get('error', 'Неизвестная ошибка')
                error_data.append({
                    'Папка': folder_name,
                    'Ошибка': error
                })
            
            # Проверяем, остались ли публикации в pending
            pending_after = self.db.count_pending_publications(user_id)
            if pending_after > 0:
                logger.warning(f"⚠️ {pending_after} публикаций остались в статусе 'pending' после генерации отчета")
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_filename = f"Отчет_{timestamp}.xlsx"
            report_path = os.path.join(user_folder, report_filename)
            
            if EXCEL_AVAILABLE:
                self._create_excel_report(report_path, success_data, error_data)
            else:
                report_filename = f"Отчет_{timestamp}.csv"
                report_path = os.path.join(user_folder, report_filename)
                self._create_csv_report(report_path, success_data, error_data)
            
            logger.info(f"📊 Отчет создан: {report_path}")
            self.cleanup_user_data(user_id, keep_report=True)
            
            with self._lock:
                del self._generating[user_id]
            
            return report_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания отчета: {e}")
            import traceback
            traceback.print_exc()
            with self._lock:
                if user_id in self._generating:
                    del self._generating[user_id]
            return None
    
    def _wait_for_links(self, user_id, publications):
        """
        Ожидает появления ссылок для публикаций со статусом 'pending'
        """
        try:
            # Находим публикации со статусом 'pending'
            pending_publications = [p for p in publications if p.get('status') == 'pending']
            
            if not pending_publications:
                logger.info("✅ Нет публикаций в статусе 'pending'")
                return
            
            logger.info(f"⏳ Ожидание ссылок для {len(pending_publications)} публикаций...")
            
            waited = 0
            completed = 0
            
            while waited < self.MAX_WAIT_TIME:
                # Проверяем каждую pending публикацию
                still_pending = []
                
                for pub in pending_publications:
                    folder_name = pub.get('folder_name')
                    # Проверяем статус в БД
                    status = self.db.check_publication_status(user_id, folder_name)
                    
                    if status == 'pending':
                        still_pending.append(folder_name)
                    elif status == 'success':
                        completed += 1
                
                if not still_pending:
                    logger.info(f"✅ Все {len(pending_publications)} публикаций получили ссылки")
                    break
                
                # Ждем
                time.sleep(self.CHECK_INTERVAL)
                waited += self.CHECK_INTERVAL
                
                # Показываем прогресс
                if waited % 10 == 0:
                    logger.info(f"⏳ Ожидание ссылок... {waited}с из {self.MAX_WAIT_TIME}с, осталось {len(still_pending)}")
            
            if waited >= self.MAX_WAIT_TIME:
                logger.warning(f"⚠️ Истекло время ожидания ({self.MAX_WAIT_TIME}с) для некоторых публикаций")
                
                # Проверяем, какие публикации так и остались без ссылок
                for pub in pending_publications:
                    folder_name = pub.get('folder_name')
                    status = self.db.check_publication_status(user_id, folder_name)
                    
                    if status == 'pending':
                        # Проверяем, не появилась ли ссылка в ad_metadata
                        metadata = self.db.get_ad_metadata(user_id, folder_name)
                        post_link = metadata.get('post_link')
                        
                        if post_link:
                            # Ссылка появилась! Обновляем статус
                            self.db.update_publication_status(user_id, folder_name, 'success')
                            logger.info(f"✅ Ссылка появилась для {folder_name}: {post_link}")
                        else:
                            # Ссылки нет - помечаем как failed
                            logger.warning(f"⚠️ Публикация {folder_name} так и не получила ссылку")
                            self.db.update_publication_status(
                                user_id, 
                                folder_name, 
                                'failed',
                                error="Ссылка не получена за отведенное время (60с)"
                            )
            
            logger.info(f"✅ Ожидание завершено. Получено {completed} ссылок из {len(pending_publications)}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка в _wait_for_links: {e}")
    
    def _create_excel_report(self, filepath, success_data, error_data):
        """Создает Excel файл"""
        try:
            wb = Workbook()
            if 'Sheet' in wb.sheetnames:
                wb.remove(wb['Sheet'])
            
            ws_success = wb.create_sheet("Отчет по публикациям", 0)
            headers = ['№', 'Дата', 'Время публикации (МСК)', 'Ссылка на пост', 
                      'Ссылка (источник)', 'Название', 'Код предложения', 'Цена в лизинге']
            
            header_font = Font(bold=True, size=11, color="FFFFFF", name="Calibri")
            header_fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
            header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            text_font = Font(size=10, name="Calibri")
            text_alignment_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
            text_alignment_center = Alignment(horizontal="center", vertical="center")
            thin_border = Border(
                left=Side(style="thin", color="D0D0D0"),
                right=Side(style="thin", color="D0D0D0"),
                top=Side(style="thin", color="D0D0D0"),
                bottom=Side(style="thin", color="D0D0D0")
            )
            link_font = Font(color="0563C1", underline="single", size=10, name="Calibri")
            
            # Заголовок
            title_cell = ws_success.cell(row=1, column=1, value="Отчет по публикациям")
            title_cell.font = Font(bold=True, size=16, name="Calibri", color="1A1A2E")
            title_cell.alignment = Alignment(horizontal="center", vertical="center")
            ws_success.merge_cells('A1:H1')
            ws_success.row_dimensions[1].height = 35
            
            # Заголовки таблицы
            for col, header in enumerate(headers, 1):
                cell = ws_success.cell(row=2, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment
                cell.border = thin_border
            ws_success.row_dimensions[2].height = 25
            
            # Данные
            for row_idx, data in enumerate(success_data, 3):
                for col_idx, key in enumerate(headers, 1):
                    value = data.get(key, '')
                    cell = ws_success.cell(row=row_idx, column=col_idx, value=value)
                    
                    if key in ['№', 'Дата', 'Время публикации (МСК)']:
                        cell.alignment = text_alignment_center
                    elif key in ['Ссылка на пост', 'Ссылка (источник)'] and value and not value.startswith('⚠️'):
                        cell.font = link_font
                        cell.alignment = text_alignment_left
                    elif key == 'Ссылка на пост' and value.startswith('⚠️'):
                        cell.font = Font(color="FF0000", size=10, name="Calibri")
                        cell.alignment = text_alignment_left
                    else:
                        cell.font = text_font
                        cell.alignment = text_alignment_left
                    
                    cell.border = thin_border
                    ws_success.row_dimensions[row_idx].height = 22
            
            # Чередование цветов
            for row_idx in range(3, len(success_data) + 3):
                if row_idx % 2 == 1:
                    for col in range(1, 9):
                        cell = ws_success.cell(row=row_idx, column=col)
                        cell.fill = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")
            
            # Ширина колонок
            column_widths = {'A': 5, 'B': 14, 'C': 18, 'D': 50, 'E': 40, 'F': 32, 'G': 18, 'H': 18}
            for col_letter, width in column_widths.items():
                ws_success.column_dimensions[col_letter].width = width
            ws_success.freeze_panes = 'A3'
            
            # Лист с ошибками
            ws_errors = wb.create_sheet("Ошибки", 1)
            error_title = ws_errors.cell(row=1, column=1, value="Ошибки публикации")
            error_title.font = Font(bold=True, size=16, name="Calibri", color="C00000")
            error_title.alignment = Alignment(horizontal="center", vertical="center")
            ws_errors.merge_cells('A1:B1')
            ws_errors.row_dimensions[1].height = 35
            
            error_headers = ['Папка', 'Ошибка']
            error_header_font = Font(bold=True, size=11, color="FFFFFF", name="Calibri")
            error_header_fill = PatternFill(start_color="C00000", end_color="C00000", fill_type="solid")
            
            for col, header in enumerate(error_headers, 1):
                cell = ws_errors.cell(row=2, column=col, value=header)
                cell.font = error_header_font
                cell.fill = error_header_fill
                cell.alignment = header_alignment
                cell.border = thin_border
            ws_errors.row_dimensions[2].height = 25
            
            if not error_data:
                cell = ws_errors.cell(row=3, column=1, value="✅ Нет ошибок")
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.font = Font(color="28A745", size=14, bold=True, name="Calibri")
                ws_errors.merge_cells('A3:B3')
                ws_errors.row_dimensions[3].height = 40
            else:
                for row_idx, data in enumerate(error_data, 3):
                    cell1 = ws_errors.cell(row=row_idx, column=1, value=data.get('Папка', ''))
                    cell1.font = text_font
                    cell1.alignment = text_alignment_left
                    cell1.border = thin_border
                    ws_errors.row_dimensions[row_idx].height = 22
                    
                    cell2 = ws_errors.cell(row=row_idx, column=2, value=data.get('Ошибка', ''))
                    cell2.font = Font(color="C00000", size=10, name="Calibri")
                    cell2.alignment = text_alignment_left
                    cell2.border = thin_border
                    
                    if row_idx % 2 == 1:
                        cell1.fill = PatternFill(start_color="FFF0F0", end_color="FFF0F0", fill_type="solid")
                        cell2.fill = PatternFill(start_color="FFF0F0", end_color="FFF0F0", fill_type="solid")
            
            ws_errors.column_dimensions['A'].width = 35
            ws_errors.column_dimensions['B'].width = 65
            ws_errors.freeze_panes = 'A3'
            
            wb.save(filepath)
            logger.info(f"✅ Excel отчет создан: {filepath}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания Excel отчета: {e}")
            raise
    
    def _create_csv_report(self, filepath, success_data, error_data):
        """Создает CSV отчет"""
        try:
            with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f, delimiter=';')
                
                writer.writerow(['=== УСПЕШНЫЕ ПУБЛИКАЦИИ ==='])
                writer.writerow(['№', 'Дата', 'Время публикации (МСК)', 'Ссылка на пост', 
                               'Ссылка (источник)', 'Название', 'Код предложения', 'Цена в лизинге'])
                
                for data in success_data:
                    writer.writerow([
                        data.get('№', ''),
                        data.get('Дата', ''),
                        data.get('Время публикации (МСК)', ''),
                        data.get('Ссылка на пост', ''),
                        data.get('Ссылка (источник)', ''),
                        data.get('Название', ''),
                        data.get('Код предложения', ''),
                        data.get('Цена в лизинге', ''),
                    ])
                
                writer.writerow([])
                writer.writerow(['=== ОШИБКИ ==='])
                writer.writerow(['Папка', 'Ошибка'])
                
                if error_data:
                    for data in error_data:
                        writer.writerow([
                            data.get('Папка', ''),
                            data.get('Ошибка', ''),
                        ])
                else:
                    writer.writerow(['✅ Нет ошибок', ''])
            
            logger.info(f"✅ CSV отчет создан: {filepath}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания CSV отчета: {e}")
            raise
    
    def cleanup_user_data(self, user_id, keep_report=True):
        """Удаляет временные данные"""
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
                    elif not item.startswith('Отчет_') and not item.startswith('Ошибки_'):
                        os.remove(item_path)
                        logger.info(f"🗑️ Удален файл: {item}")
            else:
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
                logger.info(f"🗑️ Все данные пользователя {user_id} удалены")
                
        except Exception as e:
            logger.error(f"❌ Ошибка очистки: {e}")
    
    def is_generating(self, user_id):
        """Проверяет, выполняется ли генерация отчета для пользователя"""
        with self._lock:
            if user_id in self._generating:
                elapsed = time.time() - self._generating[user_id]
                return elapsed < 120  # Считаем активной если меньше 2 минут
            return False
