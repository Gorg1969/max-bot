import os

bind = "0.0.0.0:" + os.environ.get("PORT", "3000")
workers = 1
worker_class = "gthread"
threads = 4
timeout = 600
keepalive = 5

# ОТКЛЮЧАЕМ ПЕРЕЗАПУСКИ
max_requests = 0
max_requests_jitter = 0

preload_app = False

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

worker_tmp_dir = "/dev/shm"
graceful_timeout = 30
