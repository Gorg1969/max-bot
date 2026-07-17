# gunicorn.conf.py

import os
import multiprocessing

# Настройки Gunicorn
bind = "0.0.0.0:" + os.environ.get("PORT", "3000")
workers = int(os.environ.get("WEB_CONCURRENCY", 4))
worker_class = "gthread"
threads = int(os.environ.get("THREADS", 2))
worker_connections = 1000
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 100

# Логирование
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Предзагрузка
preload_app = True

def post_fork(server, worker):
    server.log.info(f"Worker spawned (pid: {worker.pid})")
