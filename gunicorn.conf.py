# gunicorn.conf.py

import os

bind = "0.0.0.0:" + os.environ.get("PORT", "3000")

# ✅ 1 воркер для SQLite
workers = 1

# ✅ 4 потока для параллельной обработки
worker_class = "gthread"
threads = 4

timeout = 600
keepalive = 5
max_requests = 100
max_requests_jitter = 10
preload_app = False  # Отключаем для SQLite

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

worker_tmp_dir = "/dev/shm"
graceful_timeout = 30
