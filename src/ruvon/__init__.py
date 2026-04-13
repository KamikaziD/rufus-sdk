"""
Ruvon - Python Workflow SDK

High-performance workflow orchestration engine with pluggable architecture.
"""

import os
import asyncio

# Performance optimization: Use uvloop if available
# uvloop is a Cython-based asyncio event loop that's 2-4x faster
_UVLOOP_ENABLED = os.getenv("RUVON_USE_UVLOOP", "true").lower() == "true"

if _UVLOOP_ENABLED:
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        _event_loop_backend = "uvloop"
    except ImportError:
        _event_loop_backend = "asyncio (stdlib)"
else:
    _event_loop_backend = "asyncio (stdlib)"

__version__ = "0.1.2"
__all__ = [
    "Workflow",
    "WorkflowBuilder",
    "WorkflowStep",
    "HumanWorkflowStep",
    "StepContext",
]

# Import core classes for convenience
from ruvon.workflow import Workflow
from ruvon.builder import WorkflowBuilder
from ruvon.models import WorkflowStep, HumanWorkflowStep, StepContext
