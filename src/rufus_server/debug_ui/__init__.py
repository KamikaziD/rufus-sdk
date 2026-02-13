"""Debug UI for Rufus workflow visualization and debugging.

Ported from Confucius to provide visual workflow inspection,
real-time status updates, and interactive workflow execution.
"""

from .router import get_debug_ui_router

__all__ = ["get_debug_ui_router"]
