"""
Celery-decorated wrappers for cross_platform_workflows parallel tasks.

CeleryExecutor.dispatch_parallel_tasks() requires functions decorated with
@celery_app.task so they have .apply_async(). Plain Python functions in
steps.py can't be used directly as Celery parallel tasks.

Only the functions used as PARALLEL step tasks need wrappers here.
"""
import random

from ruvon.celery_app import celery_app


@celery_app.task
def check_warehouse_uk(state: dict, workflow_id: str):
    in_stock = random.random() > 0.35  # 65% in stock
    return {"stock_uk": in_stock}


@celery_app.task
def check_warehouse_eu(state: dict, workflow_id: str):
    in_stock = random.random() > 0.35
    return {"stock_eu": in_stock}
