"""
State models for the Quickstart example.

This module defines the data structure that persists throughout
the workflow execution.
"""

from pydantic import BaseModel
from typing import Optional


class GreetingState(BaseModel):
    """
    State model for the my workflow.

    Attributes:
        name: The name of the person to greet (required)
        greeting: The generated greeting message (set by Generate_Greeting step)
        formatted_output: The final formatted output (set by Format_Output step)
    """

    name: str
    greeting: Optional[str] = None
    formatted_output: Optional[str] = None
    email_sent: Optional[bool] = False
    random_event: Optional[bool] = False
