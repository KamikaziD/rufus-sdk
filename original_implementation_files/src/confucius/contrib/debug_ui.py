from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

def get_debug_ui_router() -> APIRouter:
    """
    Returns a FastAPI APIRouter that serves the main HTML page for the debug UI.
    
    Note: This router ONLY serves the HTML template. The static files (CSS, JS)
    must be mounted separately by the main application. This is done to give the
    main app full control over its URL space.
    """
    router = APIRouter()
    
    # The path to the templates is relative to this file's location.
    templates_path = Path(__file__).parent / "templates"
    
    # Configure Jinja2 to find the index.html template
    templates = Jinja2Templates(directory=templates_path)

    @router.get("/", response_class=HTMLResponse)
    async def read_root(request: Request):
        """Serves the debug UI's main page."""
        return templates.TemplateResponse("index.html", {"request": request})
        
    return router
