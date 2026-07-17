# modules/__init__.py

from .database import Database
from .file_manager import FileManager
from .publisher import Publisher
from .report_generator import ReportGenerator
from .tasks import process_folder_task, cleanup_user_task

# Добавляем APIClient для использования в воркере
class APIClient:
    def __init__(self):
        import os
        import requests
        self.token = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
        self.base_url = "https://platform-api2.max.ru"

__all__ = [
    'Database',
    'FileManager',
    'Publisher',
    'ReportGenerator',
    'APIClient',
    'process_folder_task',
    'cleanup_user_task'
]
