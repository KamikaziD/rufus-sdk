"""
Command Retry Policy

Defines retry strategies and backoff calculations for device commands.
"""

from enum import Enum
from typing import Optional
from datetime import datetime, timedelta
from pydantic import BaseModel, Field


class BackoffStrategy(str, Enum):
    """Backoff strategy for retries."""
    EXPONENTIAL = "exponential"  # Delay doubles each retry: 10s, 20s, 40s, 80s
    LINEAR = "linear"             # Delay increases linearly: 10s, 20s, 30s, 40s
    FIXED = "fixed"               # Same delay each time: 10s, 10s, 10s, 10s


class RetryPolicy(BaseModel):
    """
    Retry policy configuration for commands.

    Examples:
        # Exponential backoff (default)
        RetryPolicy(max_retries=3, initial_delay_seconds=10)

        # Linear backoff
        RetryPolicy(
            max_retries=5,
            initial_delay_seconds=30,
            backoff_strategy="linear",
            backoff_multiplier=1.0
        )

        # Fixed delay
        RetryPolicy(
            max_retries=10,
            initial_delay_seconds=60,
            backoff_strategy="fixed"
        )
    """

    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum number of retry attempts (0-10)"
    )

    initial_delay_seconds: int = Field(
        default=10,
        ge=1,
        le=3600,
        description="Initial delay before first retry (1s - 1 hour)"
    )

    backoff_strategy: BackoffStrategy = Field(
        default=BackoffStrategy.EXPONENTIAL,
        description="Backoff strategy for calculating retry delays"
    )

    backoff_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Multiplier for exponential/linear backoff (1.0-10.0)"
    )

    max_delay_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Maximum delay between retries (1 min - 24 hours)"
    )

    jitter: bool = Field(
        default=True,
        description="Add random jitter to prevent thundering herd"
    )

    def calculate_next_retry(self, retry_count: int) -> datetime:
        """
        Calculate the next retry time based on the policy.

        Args:
            retry_count: Current retry attempt number (0-indexed)

        Returns:
            Datetime for next retry attempt
        """
        import random

        if self.backoff_strategy == BackoffStrategy.EXPONENTIAL:
            # Exponential: initial * (multiplier ^ retry_count)
            delay = self.initial_delay_seconds * (self.backoff_multiplier ** retry_count)
        elif self.backoff_strategy == BackoffStrategy.LINEAR:
            # Linear: initial + (multiplier * retry_count * initial)
            delay = self.initial_delay_seconds * (1 + self.backoff_multiplier * retry_count)
        else:  # FIXED
            delay = self.initial_delay_seconds

        # Cap at max delay
        delay = min(delay, self.max_delay_seconds)

        # Add jitter (±20% random variation)
        if self.jitter:
            jitter_range = delay * 0.2
            delay += random.uniform(-jitter_range, jitter_range)

        # Ensure positive delay
        delay = max(delay, 1)

        return datetime.utcnow() + timedelta(seconds=delay)

    def should_retry(self, retry_count: int) -> bool:
        """Check if command should be retried."""
        return retry_count < self.max_retries

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "max_retries": self.max_retries,
            "initial_delay_seconds": self.initial_delay_seconds,
            "backoff_strategy": self.backoff_strategy.value,
            "backoff_multiplier": self.backoff_multiplier,
            "max_delay_seconds": self.max_delay_seconds,
            "jitter": self.jitter,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RetryPolicy":
        """Create from dictionary."""
        return cls(**data)


# Predefined retry policies for common use cases
RETRY_POLICIES = {
    "default": RetryPolicy(
        max_retries=3,
        initial_delay_seconds=10,
        backoff_strategy=BackoffStrategy.EXPONENTIAL,
    ),

    "aggressive": RetryPolicy(
        max_retries=5,
        initial_delay_seconds=5,
        backoff_strategy=BackoffStrategy.EXPONENTIAL,
        backoff_multiplier=1.5,
    ),

    "conservative": RetryPolicy(
        max_retries=2,
        initial_delay_seconds=30,
        backoff_strategy=BackoffStrategy.LINEAR,
    ),

    "persistent": RetryPolicy(
        max_retries=10,
        initial_delay_seconds=60,
        backoff_strategy=BackoffStrategy.FIXED,
        jitter=True,
    ),

    "quick": RetryPolicy(
        max_retries=3,
        initial_delay_seconds=5,
        backoff_strategy=BackoffStrategy.FIXED,
        jitter=False,
    ),
}


def get_retry_policy(name: str) -> Optional[RetryPolicy]:
    """Get a predefined retry policy by name."""
    return RETRY_POLICIES.get(name)
