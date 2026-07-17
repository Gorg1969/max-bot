# gunicorn.conf.py

import os

bind = "0.0.0.0:" + os.environ.get("PORT", "3000")
workers = 2
worker_class = "gthread"
threads = 4  # Увеличил для лучшей обработки
timeout = 600  # 10 минут на публикацию
keepalive = 5
max_requests = 100
max_requests_jitter = 10
preload_app = True

# Настройки логирования
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Дополнительные настройки для производительности
worker_tmp_dir = "/dev/shm"
graceful_timeout = 30
