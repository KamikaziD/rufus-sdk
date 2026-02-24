"""
Cloud Policy Engine

The Policy Engine is the "Symmetric Brain" of the Rufus platform. It allows
management of diverse device fleets (NVIDIA Jetsons, Mac Minis, Raspberry Pis)
through declarative policies that map hardware capabilities to artifacts.

Key Concepts:
- Policies: Declarative rules that map hardware conditions to artifacts
- Hardware Identity: Device-reported capabilities (GPU, VRAM, platform)
- Artifacts: Signed PEX bundles optimized for specific hardware
- Rollout: Canary/staged deployment strategies

Example Policy:
    {
        "policy_name": "Q1_Vision_Update",
        "rules": [
            {
                "condition": "hardware == 'NVIDIA' and vram_free >= 4096",
                "artifact": "vision_heavy_v2_tensorrt.pex"
            },
            {
                "condition": "hardware == 'APPLE_SILICON'",
                "artifact": "vision_v2_mlx.pex"
            },
            {
                "condition": "default",
                "artifact": "vision_lite_v2_onnx.pex"
            }
        ],
        "rollout": {
            "strategy": "canary",
            "percentage": 10
        }
    }
"""

import hashlib
import logging
import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================

class RolloutStrategy(str, Enum):
    """Deployment rollout strategies."""
    IMMEDIATE = "immediate"  # Deploy to all matching devices
    CANARY = "canary"  # Gradual rollout by percentage
    STAGED = "staged"  # Deploy to groups in order
    MANUAL = "manual"  # Require manual approval per device


class PolicyStatus(str, Enum):
    """Policy lifecycle status."""
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class AssignmentStatus(str, Enum):
    """Device assignment status."""
    PENDING = "pending"  # Artifact assigned, not yet downloaded
    DOWNLOADING = "downloading"  # Device is downloading artifact
    VERIFYING = "verifying"  # Device is verifying signature
    INSTALLED = "installed"  # Artifact installed and running
    FAILED = "failed"  # Installation failed
    ROLLED_BACK = "rolled_back"  # Reverted to previous version


# ============================================================================
# Policy Schema Models
# ============================================================================

class PolicyRule(BaseModel):
    """
    A single rule in a policy that maps a condition to an artifact.

    Conditions are evaluated against the device's HardwareIdentity.
    """
    condition: str = Field(
        ...,
        description="Condition expression or 'default' for fallback",
        examples=["hardware == 'NVIDIA' and vram_free >= 4096", "default"]
    )
    artifact: str = Field(
        ...,
        description="Artifact filename or path to deploy",
        examples=["vision_heavy_v2_tensorrt.pex"]
    )
    artifact_hash: Optional[str] = Field(
        None,
        description="SHA256 hash of the artifact for verification"
    )
    description: Optional[str] = Field(
        None,
        description="Human-readable description of this rule"
    )
    priority: int = Field(
        default=0,
        description="Rule priority (higher = evaluated first)"
    )

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, v: str) -> str:
        """Validate condition syntax."""
        if v == "default":
            return v

        # Basic validation - ensure it's a valid expression
        # Disallow dangerous patterns
        dangerous = ["import", "exec", "eval", "open", "__", "lambda"]
        for pattern in dangerous:
            if pattern in v.lower():
                raise ValueError(f"Dangerous pattern in condition: {pattern}")

        return v


class RolloutConfig(BaseModel):
    """Configuration for gradual rollout of policy."""
    strategy: RolloutStrategy = Field(
        default=RolloutStrategy.IMMEDIATE,
        description="Rollout strategy"
    )
    percentage: int = Field(
        default=100,
        ge=0,
        le=100,
        description="Percentage of devices to deploy to (for canary)"
    )
    failure_threshold: str = Field(
        default="5%",
        description="Maximum failure rate before halting rollout"
    )
    batch_size: int = Field(
        default=10,
        description="Number of devices per batch (for staged)"
    )
    batch_delay_seconds: int = Field(
        default=300,
        description="Delay between batches in seconds"
    )
    stages: List[str] = Field(
        default_factory=list,
        description="Device groups for staged rollout"
    )


class Policy(BaseModel):
    """
    Deployment policy that maps hardware capabilities to artifacts.

    Policies are the core abstraction for managing heterogeneous device fleets.
    """
    id: UUID = Field(default_factory=uuid4)
    policy_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique policy identifier"
    )
    description: Optional[str] = Field(
        None,
        description="Human-readable description"
    )
    version: str = Field(
        default="1.0.0",
        description="Policy version (semver)"
    )
    status: PolicyStatus = Field(
        default=PolicyStatus.DRAFT,
        description="Policy lifecycle status"
    )
    rules: List[PolicyRule] = Field(
        ...,
        min_length=1,
        description="Ordered list of condition->artifact rules"
    )
    rollout: RolloutConfig = Field(
        default_factory=RolloutConfig,
        description="Rollout configuration"
    )

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    tags: Dict[str, str] = Field(default_factory=dict)

    def get_sorted_rules(self) -> List[PolicyRule]:
        """Get rules sorted by priority (highest first), with 'default' last."""
        default_rules = [r for r in self.rules if r.condition == "default"]
        other_rules = [r for r in self.rules if r.condition != "default"]
        other_rules.sort(key=lambda r: r.priority, reverse=True)
        return other_rules + default_rules


# ============================================================================
# Device Assignment Models
# ============================================================================

class DeviceAssignment(BaseModel):
    """
    Tracks artifact assignment for a specific device.

    Records what version should be on the device vs. what is actually installed.
    """
    id: UUID = Field(default_factory=uuid4)
    device_id: str = Field(..., description="Unique device identifier")
    policy_id: UUID = Field(..., description="Policy that created this assignment")
    policy_version: str = Field(..., description="Policy version at assignment time")

    # Artifact info
    assigned_artifact: str = Field(..., description="Artifact that should be installed")
    artifact_hash: Optional[str] = Field(None, description="Expected artifact hash")
    artifact_url: Optional[str] = Field(None, description="Signed URL for download")

    # Current state
    status: AssignmentStatus = Field(default=AssignmentStatus.PENDING)
    current_artifact: Optional[str] = Field(None, description="Currently installed artifact")
    current_hash: Optional[str] = Field(None, description="Hash of current artifact")

    # Timing
    assigned_at: datetime = Field(default_factory=datetime.utcnow)
    downloaded_at: Optional[datetime] = None
    installed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None

    # Error tracking
    error_message: Optional[str] = None
    retry_count: int = Field(default=0)
    max_retries: int = Field(default=3)

    def needs_update(self) -> bool:
        """Check if device needs an artifact update."""
        if self.status in (AssignmentStatus.INSTALLED,):
            return self.current_artifact != self.assigned_artifact
        return self.status == AssignmentStatus.PENDING

    def can_retry(self) -> bool:
        """Check if assignment can be retried after failure."""
        return self.retry_count < self.max_retries


# ============================================================================
# PolicyEvaluator — Read/Evaluate Path (DIRECT CALLS — no workflow overhead)
# ============================================================================
# These operations stay as direct function calls:
#   - get_active_policies()        hot path: evaluate_condition(), evaluate_all()
#   - evaluate_condition()         called ~1k/sec on /api/v1/update-check
#   - evaluate_policy()            inline evaluation, no side effects
#   - get_assignment()             read-only
#   - should_deploy_canary()       read-only, random sampling
#
# These operations go through the PolicyRollout workflow:
#   - add_policy()                 durable write + saga compensation
#   - remove_policy()              durable delete + audit trail
#   - status updates               durable state machine transition
# ============================================================================

class PolicyEvaluator:
    """
    Evaluates policies against device hardware identities.

    The evaluator is stateless and can be run as a Lambda or FastAPI endpoint.
    It computes rule-set matches in milliseconds.
    """

    def __init__(self, policies: Optional[List[Policy]] = None):
        """
        Initialize evaluator with optional policies.

        Args:
            policies: List of policies to evaluate against
        """
        self._policies: Dict[UUID, Policy] = {}
        if policies:
            for policy in policies:
                self.add_policy(policy)

    def add_policy(self, policy: Policy) -> None:
        """Add or update a policy."""
        self._policies[policy.id] = policy
        logger.info(f"Added policy: {policy.policy_name} (v{policy.version})")

    def remove_policy(self, policy_id: UUID) -> bool:
        """Remove a policy by ID."""
        if policy_id in self._policies:
            del self._policies[policy_id]
            return True
        return False

    def get_active_policies(self) -> List[Policy]:
        """Get all active policies."""
        return [p for p in self._policies.values() if p.status == PolicyStatus.ACTIVE]

    def evaluate_condition(
        self,
        condition: str,
        hardware_identity: Dict[str, Any]
    ) -> bool:
        """
        Evaluate a condition against hardware identity.

        Args:
            condition: Condition expression
            hardware_identity: Device hardware capabilities

        Returns:
            True if condition matches
        """
        if condition == "default":
            return True

        # Build evaluation context from hardware identity
        context = {
            # Core identifiers
            "hardware": hardware_identity.get("hw", "CPU"),
            "platform": hardware_identity.get("platform", ""),
            "arch": hardware_identity.get("arch", ""),

            # Resources
            "vram_total": hardware_identity.get("vram_total") or 0,
            "vram_free": hardware_identity.get("vram_free") or 0,
            "ram_total": hardware_identity.get("ram_total") or 0,
            "ram_free": hardware_identity.get("ram_free") or 0,

            # Capabilities
            "supports_fp16": hardware_identity.get("supports_fp16", False),
            "supports_int8": hardware_identity.get("supports_int8", True),
            "supports_neural_engine": hardware_identity.get("supports_neural_engine", False),

            # Derived flags
            "has_gpu": hardware_identity.get("hw") in ("NVIDIA", "APPLE_SILICON"),
            "has_ane": hardware_identity.get("supports_neural_engine", False),
            "is_nvidia": hardware_identity.get("hw") == "NVIDIA",
            "is_apple": hardware_identity.get("hw") == "APPLE_SILICON",
            "is_edge_tpu": hardware_identity.get("hw") == "EDGE_TPU",
        }

        # Add accelerator checks
        for acc in hardware_identity.get("accelerators", []):
            context[f"has_{acc.lower()}"] = True

        try:
            # Safe evaluation
            result = eval(condition, {"__builtins__": {}}, context)
            return bool(result)
        except Exception as e:
            logger.warning(f"Condition evaluation failed: {condition} - {e}")
            return False

    def evaluate_policy(
        self,
        policy: Policy,
        hardware_identity: Dict[str, Any]
    ) -> Optional[PolicyRule]:
        """
        Evaluate a single policy against hardware identity.

        Args:
            policy: Policy to evaluate
            hardware_identity: Device hardware capabilities

        Returns:
            Matching PolicyRule or None
        """
        if policy.status != PolicyStatus.ACTIVE:
            return None

        for rule in policy.get_sorted_rules():
            if self.evaluate_condition(rule.condition, hardware_identity):
                logger.debug(
                    f"Policy {policy.policy_name}: matched rule '{rule.condition}' "
                    f"-> {rule.artifact}"
                )
                return rule

        return None

    def evaluate_all(
        self,
        hardware_identity: Dict[str, Any]
    ) -> Dict[UUID, PolicyRule]:
        """
        Evaluate all active policies against hardware identity.

        Args:
            hardware_identity: Device hardware capabilities

        Returns:
            Dict mapping policy ID to matched rule
        """
        results = {}

        for policy_id, policy in self._policies.items():
            matched_rule = self.evaluate_policy(policy, hardware_identity)
            if matched_rule:
                results[policy_id] = matched_rule

        return results

    def get_assignment(
        self,
        device_id: str,
        hardware_identity: Dict[str, Any],
        policy_id: Optional[UUID] = None
    ) -> Optional[DeviceAssignment]:
        """
        Get artifact assignment for a device.

        Args:
            device_id: Unique device identifier
            hardware_identity: Device hardware capabilities
            policy_id: Specific policy to evaluate (optional)

        Returns:
            DeviceAssignment or None if no match
        """
        if policy_id:
            policy = self._policies.get(policy_id)
            if not policy:
                return None
            rule = self.evaluate_policy(policy, hardware_identity)
            if rule:
                return DeviceAssignment(
                    device_id=device_id,
                    policy_id=policy.id,
                    policy_version=policy.version,
                    assigned_artifact=rule.artifact,
                    artifact_hash=rule.artifact_hash,
                )
            return None

        # Evaluate all policies, return first match
        for policy in self.get_active_policies():
            rule = self.evaluate_policy(policy, hardware_identity)
            if rule:
                return DeviceAssignment(
                    device_id=device_id,
                    policy_id=policy.id,
                    policy_version=policy.version,
                    assigned_artifact=rule.artifact,
                    artifact_hash=rule.artifact_hash,
                )

        return None

    def should_deploy_canary(
        self,
        device_id: str,
        policy: Policy
    ) -> bool:
        """
        Determine if device should receive canary deployment.

        Uses deterministic hashing to ensure consistent decisions.

        Args:
            device_id: Unique device identifier
            policy: Policy with rollout config

        Returns:
            True if device should receive canary deployment
        """
        if policy.rollout.strategy != RolloutStrategy.CANARY:
            return True

        # Deterministic hash for consistent decisions
        hash_input = f"{device_id}:{policy.id}:{policy.version}"
        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
        bucket = hash_value % 100

        return bucket < policy.rollout.percentage


# ============================================================================
# API Request/Response Models
# ============================================================================

class DeviceCheckIn(BaseModel):
    """Request model for device check-in."""
    device_id: str = Field(..., description="Unique device identifier")
    hw: str = Field(..., description="Hardware type (NVIDIA, APPLE_SILICON, etc.)")
    platform: str = Field(default="", description="OS platform")
    arch: str = Field(default="", description="CPU architecture")
    accelerators: List[str] = Field(default_factory=list)
    vram_total: Optional[int] = None
    vram_free: Optional[int] = None
    ram_total: Optional[int] = None
    ram_free: Optional[int] = None
    supports_fp16: bool = False
    supports_int8: bool = True
    supports_neural_engine: bool = False
    current_artifact: Optional[str] = None
    current_hash: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UpdateInstruction(BaseModel):
    """Response model for device update instruction."""
    needs_update: bool = Field(..., description="Whether device needs an update")
    artifact: Optional[str] = Field(None, description="Artifact to download")
    artifact_url: Optional[str] = Field(None, description="Signed URL for download")
    artifact_hash: Optional[str] = Field(None, description="Expected SHA256 hash")
    policy_id: Optional[UUID] = None
    policy_version: Optional[str] = None
    message: Optional[str] = None


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Enums
    "RolloutStrategy",
    "PolicyStatus",
    "AssignmentStatus",
    # Models
    "PolicyRule",
    "RolloutConfig",
    "Policy",
    "DeviceAssignment",
    "DeviceCheckIn",
    "UpdateInstruction",
    # Evaluator
    "PolicyEvaluator",
]
