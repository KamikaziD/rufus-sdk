import time
from typing import Optional
from confucius.celery_app import celery_app
from confucius.models import StepContext
from state_models import OnboardingState

# --- Onboarding Workflow Steps ---

def create_user_profile(state: OnboardingState, context: StepContext):
    """Placeholder for creating a user profile in the onboarding workflow."""
    input_data = context.validated_input
    if not input_data:
        raise ValueError("User profile input is missing from the context.")

    name = input_data.name
    email = input_data.email
    
    print(f"Creating user profile for {name} with email {email}.")
    state.name = name
    state.email = email
    state.user_id = f"USER-{int(time.time())}"
    state.email_domain = email.split('@')[1]
    return {"user_id": state.user_id}

@celery_app.task
def verify_email_address(state: dict):
    """Placeholder for verifying an email address asynchronously."""
    print(f"Verifying email address for user {state.get('user_id')}.")
    time.sleep(3)
    return {"email_verified": True}

@celery_app.task
def send_welcome_email(state: dict):
    """Placeholder for sending a welcome email asynchronously."""
    print(f"Sending welcome email to user.")
    time.sleep(2) # Simulate email sending
    return {"email_sent": True}
