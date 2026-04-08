"""Data models for the AI Workflow Builder pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ruvon.builder_ai.knowledge.raft_router import PrivacyLevel, RetrievalDecision


class RufusIntent(BaseModel):
    """Structured representation of the user's workflow intent."""
    description: str = Field(..., description="User intent paraphrased by the model")
    trigger: str = Field("manual", description="'event' | 'schedule' | 'manual' | 'webhook'")
    domain: str = Field("", description="e.g. 'bid-evaluation', 'compliance-check'")
    edge_required: bool = Field(False, description="Must run offline-capable?")
    ambiguities: List[str] = Field(default_factory=list, description="Unclear parts that need clarification")


class StepPlanEntry(BaseModel):
    """A single step in the planned workflow."""
    id: str
    type: str = Field(..., description="Rufus step type string, e.g. 'AI_LLM_INFERENCE'")
    label: str = Field(..., description="Human-readable description of what this step does")


class StepPlanEdge(BaseModel):
    """A directed edge between two steps in the plan."""
    from_step: str = Field(..., description="Source step id")
    to_step: str = Field(..., description="Destination step id")
    condition: Optional[str] = Field(None, description="Optional condition expression")


class StepPlan(BaseModel):
    """Ordered step plan with directed edges."""
    steps: List[StepPlanEntry]
    edges: List[StepPlanEdge] = Field(default_factory=list)


class LintResult(BaseModel):
    """Result for a single governance rule check."""
    rule_id: str = Field(..., description="e.g. 'GOV-001'")
    severity: str = Field(..., description="'ERROR' | 'WARN' | 'INFO'")
    message: str
    passed: bool


class LintReport(BaseModel):
    """Full governance lint report for a generated workflow."""
    results: List[LintResult] = Field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def warned(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.severity == "WARN")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.severity == "ERROR")

    @property
    def has_errors(self) -> bool:
        return self.failed > 0

    def summary(self) -> str:
        total = len(self.results)
        return f"{self.passed}/{total} rules passed, {self.warned} warnings, {self.failed} errors"


class BuildResult(BaseModel):
    """Output from a full AIWorkflowBuilder.build() call."""
    yaml: Optional[str] = Field(None, description="Generated workflow YAML string")
    workflow_dict: Optional[Dict[str, Any]] = Field(None, description="Validated workflow as a dict")
    lint_report: Optional[LintReport] = Field(None, description="Governance lint results")
    needs_clarification: bool = Field(False, description="True when the pipeline needs more info from the user")
    questions: List[str] = Field(default_factory=list, description="Clarifying questions to ask the user")
    errors: List[str] = Field(default_factory=list, description="Schema validation errors")
    # Stub generation
    stubs_py: Optional[str] = Field(None, description="Generated Python step function stubs (.py source)")
    # Quality gate audit trail (mirrors browser_demo quality field)
    yaml_gate_attempts: int = Field(1, description="Number of YAML generation attempts needed")
    stub_gate_attempts: int = Field(1, description="Number of stub validation attempts needed")
    quality: str = Field("GOOD", description="'GOOD' | 'PARTIAL' | 'FAILED'")
    # RAG/RAFT knowledge base fields
    retrieval_decision: Optional[Any] = Field(
        None,
        description="RetrievalDecision from RAFTRouter — strategy, confidence, chunks used",
    )
    privacy_level: str = Field(
        "balanced",
        description="Privacy tier used: 'strict' | 'balanced' | 'cloud'",
    )
    pii_redactions: int = Field(0, description="Number of PII redactions applied before cloud calls")
    chunks_sent_to_cloud: bool = Field(False, description="Whether doc chunks were sent to a cloud LLM")
