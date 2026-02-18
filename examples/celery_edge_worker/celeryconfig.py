"""
Celery Configuration for Rufus Edge Workers

This configures Celery with Redis broker and result backend.
Workers will automatically fall back to SQLite SAF when Redis is unavailable.
"""

import os

# Broker settings
broker_url = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
result_backend = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

# Task settings
task_serializer = 'json'
accept_content = ['json']
result_serializer = 'json'
timezone = 'UTC'
enable_utc = True

# Worker settings
worker_prefetch_multiplier = 4
worker_max_tasks_per_child = 1000
task_acks_late = True
task_reject_on_worker_lost = True

# Task result settings
result_expires = 3600  # 1 hour

# Task routing
task_routes = {
    'rufus_worker_edge.check_fraud': {'queue': 'fraud-check'},
    'rufus_worker_edge.llm_inference': {'queue': 'llm-inference'},
}

# Task time limits
task_soft_time_limit = 300  # 5 minutes
task_time_limit = 600  # 10 minutes

# Beat schedule (for periodic tasks)
beat_schedule = {
    'sync-saf-queue': {
        'task': 'rufus_worker_edge.sync_saf_periodic',
        'schedule': 60.0,  # Every 60 seconds
    },
}
