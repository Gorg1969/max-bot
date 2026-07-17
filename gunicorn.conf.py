# gunicorn.conf.py

import os
import multiprocessing

# Настройки Gunicorn
bind = "0.0.0.0:3000"
workers = 4  # Количество воркеров
worker_class = "gthread"  # Используем gthread для поддержки потоков
threads = 2  # Потоков на воркер
worker_connections = 1000
timeout = 120  # Таймаут запроса
keepalive = 5
max_requests = 1000
max_requests_jitter = 100

# Логирование
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Для здоровья приложения
preload_app = True

def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)" % worker.pid)

def pre_fork(server, worker):
    pass
