"""Debug UI Router for Ruvon Server.

Provides a visual interface for:
- Starting workflows
- Viewing workflow status and execution history
- Inspecting workflow state
- Manually executing workflow steps
- Viewing system metrics
- Debugging failed workflows

Ported from Confucius contrib/debug_ui.py
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path


def get_debug_ui_router() -> APIRouter:
    """
    Returns a FastAPI APIRouter that serves the main HTML page for the debug UI.

    Note: This router ONLY serves the HTML template. The static files (CSS, JS, images)
    must be mounted separately by the main application using:

        from fastapi.staticfiles import StaticFiles
        app.mount("/static", StaticFiles(directory="path/to/static"), name="static")

    This separation gives the main app full control over its URL space and static file serving.

    Usage:
        from ruvon_server.debug_ui import get_debug_ui_router
        from fastapi.staticfiles import StaticFiles

        app = FastAPI()

        # Mount static files
        static_path = Path(__file__).parent / "debug_ui" / "static"
        app.mount("/static", StaticFiles(directory=static_path), name="static")

        # Include debug UI router
        app.include_router(get_debug_ui_router(), prefix="/debug", tags=["debug-ui"])
    """
    router = APIRouter()

    # The path to the templates is relative to this file's location
    templates_path = Path(__file__).parent / "templates"

    if not templates_path.exists():
        raise RuntimeError(
            f"Debug UI templates directory not found at {templates_path}. "
            "Ensure templates are copied from confucius/src/confucius/contrib/templates/"
        )

    # Configure Jinja2 to find the index.html template
    templates = Jinja2Templates(directory=templates_path)

    @router.get("/", response_class=HTMLResponse)
    async def debug_ui_root(request: Request):
        """Serves the debug UI's main page."""
        return templates.TemplateResponse("index.html", {"request": request})

    @router.get("/workflows", response_class=HTMLResponse)
    async def debug_ui_workflows(request: Request):
        """Alias for the debug UI (workflow listing)."""
        return templates.TemplateResponse("index.html", {"request": request})

    return router
