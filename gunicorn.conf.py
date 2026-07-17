# gunicorn.conf.py

import os

bind = "0.0.0.0:" + os.environ.get("PORT", "3000")
workers = 2
worker_class = "gthread"
threads = 2
timeout = 300
keepalive = 5
max_requests = 1000

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
preload_app = True
