"""
Gunicorn configuration for ShopSage AI.

Dynamically provisions Uvicorn workers based on CPU core count to
maximize throughput in a production environment.
"""

import multiprocessing
import os

# Server socket
bind = os.getenv("BIND", "0.0.0.0:8000")
backlog = 2048

# Worker processes
# Calculate workers based on CPU cores. Usually (cores * 2) + 1 is recommended,
# but for memory-heavy ML apps, we might constrain it slightly.
cores = multiprocessing.cpu_count()
# Use a minimum of 2 workers, up to cores * 2 + 1
workers = int(os.getenv("GUNICORN_WORKERS", max(2, cores * 2 + 1)))

# Worker class for FastAPI
worker_class = "uvicorn.workers.UvicornWorker"

# Timeouts
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
keepalive = 5

# Logging
# Use the accesslog format to pipe to stdout so it can be picked up by
# structlog / datadog / kibana easily
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# Request headers
forwarded_allow_ips = "*"
proxy_allow_ips = "*"

# Pre-loading application code to save memory
preload_app = True

def on_starting(server):
    server.log.info(f"Starting Gunicorn with {workers} workers on {bind}")

def worker_exit(server, worker):
    server.log.info(f"Worker {worker.pid} exited")
