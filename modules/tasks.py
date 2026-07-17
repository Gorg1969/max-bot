# modules/tasks.py

import logging
import time
import os
import json
from datetime import datetime
from .publisher import Publisher
from .file_manager import FileManager
from .database import Database

logger = logging.getLogger(__name__)

# Глобальные объекты (будут инициализированы в воркере)
_db = None
_fm = None
_publisher = None
_api = None

def init_globals(api):
    """Инициализация глобальных объектов в воркере"""
    global _db, _fm, _publisher, _api
    _api = api
    _db = Database()
    _fm = FileManager("/app/data")
    _publisher = Publisher(_api, _fm, _db)

def process_folder_task(user_id, folder_data, job_id):
    """
    RQ задача для обработки одной папки
    
    Args:
        user_id: ID пользователя
        folder_data: Данные папки (folder_name, ad_text, metadata_text, images)
        job_id: ID задачи для отслеживания
    """
    try:
        logger.info(f"🔵 Задача {job_id}: Начало обработки папки для пользователя {user_id}")
        
        folder_name = folder_data.get('folderName')
        ad_text = folder_data.get('adText')
        metadata_text = folder_data.get('metadataText')
        images = folder_data.get('images', [])
        
        if not folder_name or not ad_text:
            logger.error(f"❌ Задача {job_id}: Нет folder_name или ad_text")
            return {
                'success': False,
                'message': 'Нет folder_name или ad_text',
                'folder_name': folder_name
            }
        
        # Публикуем папку
        success, message = _publisher.publish_single_folder(
            user_id, folder_name, ad_text, metadata_text, images
        )
        
        result = {
            'success': success,
            'message': message,
            'folder_name': folder_name,
            'job_id': job_id
        }
        
        if success:
            logger.info(f"✅ Задача {job_id}: Успешно обработана папка {folder_name}")
        else:
            logger.error(f"❌ Задача {job_id}: Ошибка: {message}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Задача {job_id}: Критическая ошибка - {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'message': str(e),
            'folder_name': folder_data.get('folderName', 'unknown'),
            'job_id': job_id
        }

def cleanup_user_task(user_id):
    """Задача для очистки данных пользователя"""
    try:
        logger.info(f"🧹 Задача очистки для пользователя {user_id}")
        if _fm:
            user_folder = _fm.get_user_folder(user_id)
            if os.path.exists(user_folder):
                import shutil
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
                logger.info(f"🗑️ Удалены файлы пользователя {user_id}")
        return {'success': True, 'message': f'Данные пользователя {user_id} очищены'}
    except Exception as e:
        logger.error(f"❌ Ошибка очистки: {e}")
        return {'success': False, 'message': str(e)}
