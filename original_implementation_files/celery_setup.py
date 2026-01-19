import sys
import os
from celery.signals import worker_process_init
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def configure_celery_app():
    """
    Configures the global celery_app instance with settings for the example application.
    This function can be called by both the celery worker entrypoint and the main
    FastAPI application to ensure consistent configuration.
    """
    # Add the src directory to the Python path to allow importing the confucius package.
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

    from confucius.celery_app import celery_app
    return celery_app

# When this file is used as the entrypoint for a Celery worker,
# configure the app immediately.
celery_app = configure_celery_app()

@worker_process_init.connect
def init_worker(**kwargs):
    """
    Reset PostgreSQL connection pool in each worker process after fork.
    This is necessary because connection pools cannot be shared across processes.
    """
    # Reset the PostgreSQL store singleton
    import confucius.persistence_postgres as pg_module
    pg_module._postgres_store = None