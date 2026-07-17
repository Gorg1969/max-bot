# worker.py

import os
import logging
import sys
from rq import Worker, Queue, Connection
from redis import Redis
from modules.tasks import init_globals

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO")),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ИЗ ОКРУЖЕНИЯ ==========
# ✅ ТОЛЬКО ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ!
TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
MAX_API_URL = os.environ.get("MAX_API_URL", "https://platform-api2.max.ru")

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН в переменных окружения!")
    sys.exit(1)

logger.info(f"✅ Токен загружен из окружения (первые 10 символов): {TOKEN[:10]}...")

# ========== КЛАСС API КЛИЕНТА ==========
class APIClient:
    def __init__(self):
        self.token = TOKEN
        self.base_url = MAX_API_URL

# ========== ИНИЦИАЛИЗАЦИЯ ==========
api_client = APIClient()
init_globals(api_client)

# Подключение к Redis
try:
    redis_conn = Redis.from_url(REDIS_URL)
    logger.info(f"✅ Подключение к Redis: {REDIS_URL}")
except Exception as e:
    logger.error(f"❌ Ошибка подключения к Redis: {e}")
    sys.exit(1)

# ========== ЗАПУСК ВОРКЕРА ==========
if __name__ == '__main__':
    logger.info("🚀 Запуск RQ воркера...")
    
    with Connection(redis_conn):
        worker = Worker(
            ['default'],
            connection=redis_conn,
            log_job_description=True
        )
        worker.work(with_scheduler=True)
