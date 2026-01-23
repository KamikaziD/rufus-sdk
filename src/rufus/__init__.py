"""
Rufus - Python Workflow SDK

High-performance workflow orchestration engine with pluggable architecture.
"""

import os
import asyncio

# Performance optimization: Use uvloop if available
# uvloop is a Cython-based asyncio event loop that's 2-4x faster
_UVLOOP_ENABLED = os.getenv("RUFUS_USE_UVLOOP", "true").lower() == "true"

if _UVLOOP_ENABLED:
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        _event_loop_backend = "uvloop"
    except ImportError:
        _event_loop_backend = "asyncio (stdlib)"
else:
    _event_loop_backend = "asyncio (stdlib)"

__version__ = "0.1.0"
__all__ = [
    "Workflow",
    "WorkflowBuilder",
    "WorkflowStep",
    "StepContext",
]

# Import core classes for convenience
from rufus.workflow import Workflow
from rufus.builder import WorkflowBuilder
from rufus.models import WorkflowStep, StepContext
