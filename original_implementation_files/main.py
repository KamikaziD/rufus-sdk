import sys
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import importlib.resources
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the src directory to the Python path to allow importing the confucius package.
# In a real application, you would install the package via pip.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

try:
    from celery_setup import configure_celery_app
    from confucius.workflow_loader import WorkflowBuilder
    from confucius.routers import get_workflow_router
    from confucius.contrib.debug_ui import get_debug_ui_router
    # Import the static directory itself as a package
    from confucius.contrib import static as contrib_static
except ImportError as e:
    print(f"Error: Could not import required modules: {e}")
    print("Please ensure that the 'src' directory is in your Python path or that the package is installed via 'pip install -e .'.")
    sys.exit(1)

from prometheus_client import make_asgi_app
from fastapi.responses import Response

# Rate Limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# --- Application Setup ---

# 1. Configure the Celery app instance.
# This is crucial to ensure the web server (task publisher) has the result backend configured.
configure_celery_app()

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Confucius Workflow Engine - Example Application")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

# Prometheus Metrics Endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# 2. Initialize the WorkflowBuilder with the path to this app's config
app_workflow_builder = WorkflowBuilder(registry_path="config/workflow_registry.yaml")

# 3. Get the pre-built API router from the confucius package
workflow_api_router = get_workflow_router(app_workflow_builder, limiter=limiter)
app.include_router(workflow_api_router)

# 4. Mount the static files for the debug UI
# This uses importlib.resources to safely locate the packaged static files
with importlib.resources.path(contrib_static, '') as static_path:
    app.mount("/static", StaticFiles(directory=static_path), name="confucius_static")

# 5. (Optional) Include the debug UI router for the HTML page
debug_ui_router = get_debug_ui_router()
app.include_router(debug_ui_router, tags=["Debug UI"])


# To run this application:
# uvicorn main:app --reload
#
# The API will be available at /api/v1/...
# The Debug UI will be available at /

