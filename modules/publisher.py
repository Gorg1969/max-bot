import time
import logging
from typing import Dict, List, Optional
from modules.google_drive import GoogleDriveStorage
from modules.scheduler import Scheduler

logger = logging.getLogger(__name__)

class Publisher:
    """Управление публикацией постов"""
    
    def __init__(self, user_id: int, storage: GoogleDriveStorage, api_sender, scheduler: Scheduler):
        self.user_id = user_id
        self.storage = storage
        self.api = api_sender
        self.scheduler = scheduler
        self.is_running = False
    
    def start_publication(self, folder_url: str):
        """Запуск публикации"""
        # 1. Извлекаем folder_id из URL
        folder_id = self.storage.get_folder_id_from_url(folder_url)
        if not folder_id:
            logger.error(f"❌ Неверная ссылка: {folder_url}")
            return
        
        # 2. Получаем список подпапок
        subfolders = self.storage.list_subfolders(folder_id)
        if not subfolders:
            logger.warning(f"⚠️ Нет подпапок в: {folder_id}")
            self.api.send_message(self.user_id, "❌ В корневой папке нет подпапок.")
            return
        
        # 3. Создаём папку для swap-файлов
        swap_folder_id = self.storage.get_or_create_swap_folder(folder_id)
        
        # 4. Проверяем, не запущена ли уже публикация
        existing_data = self.storage.read_swap_file(swap_folder_id, self.user_id)
        if existing_data and existing_data.get('status') == 'running':
            self.api.send_message(self.user_id, "⚠️ Публикация уже запущена. Дождитесь завершения.")
            return
        
        # 5. Создаём файл подкачки
        swap_data = {
            "user_id": self.user_id,
            "root_folder_id": folder_id,
            "subfolders": subfolders,
            "current_index": 0,
            "status": "running",
            "started_at": time.strftime('%Y-%m-%d %H:%M:%S'),
            "published_count": 0,
            "total_count": len(subfolders),
            "last_published": None,
            "error_message": None,
            "delay": 120,      # 2 минуты между постами
            "batch_size": 10,   # 10 постов в батче
            "batch_pause": 300  # 5 минут паузы после 10 постов
        }
        self.storage.write_swap_file(swap_folder_id, self.user_id, swap_data)
        
        # 6. Уведомляем пользователя
        self.api.send_message(
            self.user_id,
            f"✅ **Публикация запущена!**\n\n"
            f"📁 Найдено папок: {len(subfolders)}\n"
            f"⏱️ Задержка между постами: 2 минуты\n"
            f"📊 Пауза после 10 постов: 5 минут\n\n"
            f"Бот будет публиковать в фоновом режиме. Вы можете закрыть MAX."
        )
        
        # 7. Запускаем публикацию в фоне
        self.is_running = True
        self.scheduler.schedule_task(
            task_id=f"pub_{self.user_id}",
            callback=self._process_publication,
            swap_folder_id=swap_folder_id
        )
    
    def _process_publication(self, swap_folder_id: str):
        """Основной цикл публикации (выполняется в фоне)"""
        try:
            while self.is_running:
                # 1. Читаем файл подкачки
                swap_data = self.storage.read_swap_file(swap_folder_id, self.user_id)
                if not swap_data:
                    break
                
                # 2. Проверяем статус
                if swap_data['status'] in ['finished', 'error']:
                    break
                
                # 3. Получаем текущую подпапку
                current_index = swap_data['current_index']
                subfolders = swap_data['subfolders']
                
                if current_index >= len(subfolders):
                    swap_data['status'] = 'finished'
                    self.storage.write_swap_file(swap_folder_id, self.user_id, swap_data)
                    break
                
                subfolder = subfolders[current_index]
                
                # 4. Извлекаем ID группы из названия
                group_id = self._extract_group_id(subfolder['name'])
                if not group_id:
                    logger.warning(f"⚠️ Не удалось найти ID группы в: {subfolder['name']}")
                    swap_data['current_index'] += 1
                    swap_data['error_message'] = f"Нет ID группы: {subfolder['name']}"
                    self.storage.write_swap_file(swap_folder_id, self.user_id, swap_data)
                    continue
                
                # 5. Публикуем папку
                success = self._publish_folder(subfolder['id'], group_id, swap_folder_id)
                
                # 6. Обновляем статус
                if success:
                    swap_data['published_count'] += 1
                    swap_data['last_published'] = time.strftime('%Y-%m-%d %H:%M:%S')
                    logger.info(f"✅ Опубликовано: {subfolder['name']}")
                else:
                    swap_data['error_message'] = f"Ошибка: {subfolder['name']}"
                    logger.error(f"❌ Ошибка публикации: {subfolder['name']}")
                
                swap_data['current_index'] += 1
                self.storage.write_swap_file(swap_folder_id, self.user_id, swap_data)
                
                # 7. Пауза перед следующим постом
                if self.is_running and current_index < len(subfolders) - 1:
                    delay = swap_data.get('delay', 120)
                    time.sleep(delay)
                
                # 8. Пауза после батча (каждые 10 постов)
                if swap_data['published_count'] % 10 == 0 and swap_data['published_count'] > 0:
                    logger.info(f"⏳ Пауза 5 минут после {swap_data['published_count']} постов")
                    time.sleep(300)
            
            # 9. Обработка завершения
            self._finish_publication(swap_folder_id)
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
            self.api.send_message(self.user_id, f"❌ Ошибка публикации: {e}")
            self.is_running = False
    
    def _finish_publication(self, swap_folder_id: str):
        """Завершение публикации"""
        # 1. Читаем финальный файл подкачки
        swap_data = self.storage.read_swap_file(swap_folder_id, self.user_id)
        
        # 2. Формируем сообщение
        if swap_data and swap_data['status'] == 'finished':
            msg = (
                f"✅ **РАЗМЕЩЕНИЕ ЗАКОНЧЕНО!**\n\n"
                f"📁 Всего папок: {swap_data['total_count']}\n"
                f"✅ Опубликовано: {swap_data['published_count']}\n"
                f"📅 Начало: {swap_data['started_at']}\n"
                f"⏱️ Последний пост: {swap_data['last_published']}\n"
                f"📊 Ошибок: {'Есть' if swap_data.get('error_message') else 'Нет'}"
            )
            if swap_data.get('error_message'):
                msg += f"\n\n⚠️ Последняя ошибка: {swap_data['error_message']}"
        else:
            msg = "⚠️ Публикация завершена с ошибками. Проверьте логи."
        
        # 3. Отправляем уведомление пользователю
        self.api.send_message(self.user_id, msg)
        
        # 4. Удаляем файл подкачки
        self.storage.delete_swap_file(swap_folder_id, self.user_id)
        
        # 5. Очищаем временные файлы (если есть)
        # (в Google DriveStorage добавить метод cleanup_temp)
        
        self.is_running = False
        logger.info(f"✅ Публикация завершена для пользователя {self.user_id}")
    
    def _extract_group_id(self, folder_name: str) -> Optional[str]:
        """Извлечение ID группы из названия папки"""
        import re
        match = re.search(r'-(\d+)', folder_name)
        return match.group(1) if match else None
    
    def _publish_folder(self, folder_id: str, group_id: str, swap_folder_id: str) -> bool:
        """Публикация одной папки"""
        try:
            # 1. Получаем список файлов
            files = self.storage.list_files_in_folder(folder_id)
            if not files:
                return False
            
            # 2. Сортируем изображения
            images = [f for f in files if f['name'].lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))][:10]
            
            # 3. Находим info.txt
            info_file = next((f for f in files if f['name'].lower() == 'info.txt'), None)
            if not info_file:
                logger.warning(f"⚠️ Нет info.txt в папке {folder_id}")
                return False
            
            # 4. Скачиваем info.txt
            info_content = self.storage.download_text_file(info_file['id'])
            if not info_content:
                return False
            
            # 5. Сначала публикуем текст (для контекста)
            if info_content:
                self.api.send_message(group_id, info_content)
            
            # 6. Затем публикуем изображения
            if images:
                # Отправляем первое изображение с текстом
                first_image = images[0]
                image_data = self.storage.download_image(first_image['id'], first_image['name'])
                if image_data:
                    self.api.send_photo(group_id, image_data, caption=info_content[:500])
                
                # Остальные изображения отправляем без текста
                for image in images[1:]:
                    image_data = self.storage.download_image(image['id'], image['name'])
                    if image_data:
                        self.api.send_photo(group_id, image_data)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации папки {folder_id}: {e}")
            return False
    
    def stop_publication(self):
        """Остановка публикации"""
        self.is_running = False
        self.api.send_message(self.user_id, "⏹️ Публикация остановлена.")
