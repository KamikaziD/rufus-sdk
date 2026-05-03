"""
Celery tasks for workflow examples.
"""
from ruvon.celery_app import celery_app

# Import all tasks to register them with Celery
from tasks.payment_tasks import (
    process_payment_task,
    send_receipt_task,
    charge_payment_task
)
from tasks.notification_tasks import (
    send_email_task,
    send_sms_task,
    send_push_notification_task
)
from tasks.validation_tasks import (
    validate_card_task,
    check_credit_task,
    check_fraud_task,
    check_limit_task
)

__all__ = [
    'celery_app',
    'process_payment_task',
    'send_receipt_task',
    'charge_payment_task',
    'send_email_task',
    'send_sms_task',
    'send_push_notification_task',
    'validate_card_task',
    'check_credit_task',
    'check_fraud_task',
    'check_limit_task',
]
