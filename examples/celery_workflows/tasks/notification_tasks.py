"""
Notification tasks for email, SMS, and push notifications.

These tasks can run in parallel as a sub-workflow.
"""
import time
import random
from rufus.celery_app import celery_app


@celery_app.task
def send_email_task(state: dict, workflow_id: str):
    """
    Sends email notification.

    In production, use SendGrid, AWS SES, Mailgun, etc.
    """
    print(f"[EMAIL] Sending email notification")

    email = state.get("user_email", "unknown@example.com")
    message = state.get("message", "Your order has been processed")
    order_id = state.get("order_id", "unknown")

    # Simulate email API call
    time.sleep(random.uniform(1, 2))

    message_id = f"email_{workflow_id[:8]}_{int(time.time())}"

    print(f"[EMAIL] Email sent to {email}")
    print(f"[EMAIL] Message ID: {message_id}")

    return {
        "email_sent": True,
        "email_message_id": message_id,
        "email_recipient": email
    }


@celery_app.task
def send_sms_task(state: dict, workflow_id: str):
    """
    Sends SMS notification.

    In production, use Twilio, AWS SNS, etc.
    """
    print(f"[SMS] Sending SMS notification")

    phone = state.get("user_phone", "+1234567890")
    message = state.get("message", "Your order has been processed")
    order_id = state.get("order_id", "unknown")

    # Simulate SMS API call
    time.sleep(random.uniform(1, 2))

    message_id = f"sms_{workflow_id[:8]}_{int(time.time())}"

    print(f"[SMS] SMS sent to {phone}")
    print(f"[SMS] Message ID: {message_id}")

    return {
        "sms_sent": True,
        "sms_message_id": message_id,
        "sms_recipient": phone
    }


@celery_app.task
def send_push_notification_task(state: dict, workflow_id: str):
    """
    Sends push notification to mobile device.

    In production, use Firebase Cloud Messaging, OneSignal, etc.
    """
    print(f"[PUSH] Sending push notification")

    device_token = state.get("user_device_token", "device_token_abc123")
    message = state.get("message", "Your order has been processed")
    order_id = state.get("order_id", "unknown")

    # Simulate push notification API call
    time.sleep(random.uniform(1, 2))

    message_id = f"push_{workflow_id[:8]}_{int(time.time())}"

    print(f"[PUSH] Push notification sent to device {device_token[:20]}...")
    print(f"[PUSH] Message ID: {message_id}")

    return {
        "push_sent": True,
        "push_message_id": message_id,
        "push_device_token": device_token
    }
