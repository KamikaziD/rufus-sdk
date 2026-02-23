"""Minimal state model and step functions for workflow endpoint tests."""
from pydantic import BaseModel
from typing import Any


class TestState(BaseModel):
    pass


def noop_step(state: Any, context: Any, **kwargs) -> dict:
    """A no-op step function that simply returns an empty dict."""
    return {}
