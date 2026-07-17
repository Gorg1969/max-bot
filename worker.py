# worker.py

import os
import logging
import sys
from rq import Worker, Queue, Connection
from redis import Redis
from modules.tasks import init_globals
from modules import APIClient

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Переменные окружения
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")
    sys.exit(1)

# Инициализация API клиента
api_client = APIClient()

# Инициализация глобальных объектов для задач
init_globals(api_client)

# Подключение к Redis
redis_conn = Redis.from_url(REDIS_URL)

if __name__ == '__main__':
    logger.info("🚀 Запуск RQ воркера...")
    
    with Connection(redis_conn):
        worker = Worker(
            ['default'],
            connection=redis_conn,
            log_job_description=True
        )
        worker.work(with_scheduler=True)
