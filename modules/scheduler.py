import time
import threading
from typing import Dict, Callable

class Scheduler:
    """Управление очередью публикаций с задержками"""
    
    def __init__(self, delay: int = 120, batch_size: int = 10, batch_pause: int = 300):
        self.delay = delay              # Задержка между постами (сек)
        self.batch_size = batch_size    # Постов в батче
        self.batch_pause = batch_pause  # Пауза после батча (сек)
        self.is_paused = False
        self.running_tasks = {}
    
    def schedule_task(self, task_id: str, callback: Callable, *args, **kwargs):
        """Запуск задачи с задержкой"""
        if task_id not in self.running_tasks:
            thread = threading.Thread(target=self._run_task, args=(task_id, callback, *args), kwargs=kwargs)
            thread.daemon = True
            self.running_tasks[task_id] = thread
            thread.start()
    
    def _run_task(self, task_id: str, callback: Callable, *args, **kwargs):
        """Выполнение задачи с контролем времени"""
        try:
            callback(*args, **kwargs)
        except Exception as e:
            print(f"⚠️ Ошибка в задаче {task_id}: {e}")
        finally:
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
    
    def pause(self):
        """Приостановка всех задач"""
        self.is_paused = True
    
    def resume(self):
        """Возобновление всех задач"""
        self.is_paused = False
    
    def get_status(self) -> Dict:
        """Получение статуса шедулера"""
        return {
            "active_tasks": len(self.running_tasks),
            "is_paused": self.is_paused,
            "delay": self.delay,
            "batch_size": self.batch_size,
            "batch_pause": self.batch_pause
        }
