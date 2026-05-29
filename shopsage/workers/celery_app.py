import os
from celery import Celery

# Use Redis as the message broker and backend, default to local if not set
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "shopsage_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["shopsage.workers.tasks"]
)

# Optional configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Route certain tasks to specific queues if needed later:
    # task_routes={
    #     'shopsage.workers.tasks.scrape_*': {'queue': 'scraping'},
    # }
)

if __name__ == "__main__":
    celery_app.start()
