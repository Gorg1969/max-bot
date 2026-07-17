# worker.py

import os
import logging
import sys
from rq import Worker, Queue, Connection
from redis import Redis
from modules.tasks import init_globals

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")
    sys.exit(1)

class APIClient:
    def __init__(self):
        self.token = TOKEN
        self.base_url = "https://platform-api2.max.ru"

init_globals(APIClient())

redis_conn = Redis.from_url(REDIS_URL)

if __name__ == '__main__':
    logger.info("🚀 Запуск RQ воркера...")
    with Connection(redis_conn):
        worker = Worker(['default'], connection=redis_conn)
        worker.work(with_scheduler=True)
