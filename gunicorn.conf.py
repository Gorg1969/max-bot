# gunicorn.conf.py - оптимизированный для нескольких пользователей

import os

bind = "0.0.0.0:" + os.environ.get("PORT", "3000")

# Количество воркеров = количество ядер CPU * 2 + 1
workers = int(os.environ.get("GUNICORN_WORKERS", 3))

# Используем gthread для лучшей обработки
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 4))

timeout = 600  # 10 минут
keepalive = 5
max_requests = 100
max_requests_jitter = 10

# Включаем preload_app - все воркеры используют один экземпляр БД
preload_app = True

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Дополнительные оптимизации
worker_tmp_dir = "/dev/shm"
graceful_timeout = 30

# Запуск с preload
def when_ready(server):
    server.log.info("🚀 Gunicorn готов к работе!")

def post_fork(server, worker):
    server.log.info(f"🔧 Воркер {worker.pid} запущен")
