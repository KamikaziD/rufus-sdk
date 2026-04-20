"""Tests for the 6 new AI Workflow Builder step types.

Covers:
- Model instantiation and validation
- builder.py YAML → step class round-trip
- workflow.py execution with mocked providers
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from ruvon.models import (
    AILLMInferenceConfig, AILLMInferenceWorkflowStep,
    HumanApprovalConfig, HumanApprovalWorkflowStep,
    AuditEmitConfig, AuditEmitWorkflowStep,
    ComplianceCheckConfig, ComplianceCheckWorkflowStep,
    EdgeModelCallConfig, EdgeModelCallWorkflowStep,
    WorkflowBuilderMetaConfig, WorkflowBuilderMetaStep,
    WorkflowPauseDirective,
    MergeStrategy, MergeConflictBehavior,
)
from ruvon.builder import WorkflowBuilder


# ---------------------------------------------------------------------------
# Model instantiation tests
# ---------------------------------------------------------------------------

class TestAILLMInferenceConfig:
    def test_defaults(self):
        cfg = AILLMInferenceConfig(model="claude-sonnet-4-6", system_prompt="You are helpful", user_prompt="Hello")
        assert cfg.model_location == "cloud"
        assert cfg.temperature == 0.3
        assert cfg.pii_detected is False

    def test_ollama_location(self):
        cfg = AILLMInferenceConfig(
            model="llama3", model_location="ollama",
            system_prompt="s", user_prompt="u",
            ollama_base_url="http://custom:11434",
        )
        assert cfg.model_location == "ollama"
        assert cfg.ollama_base_url == "http://custom:11434"

    def test_step_instantiation(self):
        cfg = AILLMInferenceConfig(model="claude-sonnet-4-6", system_prompt="s", user_prompt="u")
        step = AILLMInferenceWorkflowStep(name="TestLLM", llm_config=cfg)
        assert step.name == "TestLLM"
        assert step.merge_strategy == MergeStrategy.SHALLOW


class TestHumanApprovalConfig:
    def test_defaults(self):
        cfg = HumanApprovalConfig(title="Review Bid")
        assert cfg.timeout_hours == 24
        assert cfg.on_timeout == "auto_reject"
        assert cfg.channels == []

    def test_full_config(self):
        cfg = HumanApprovalConfig(
            title="Approval",
            approvers=["role:procurement"],
            timeout_hours=48,
            on_timeout="escalate",
            escalate_to="manager",
            channels=["slack", "email"],
        )
        assert cfg.on_timeout == "escalate"
        assert len(cfg.channels) == 2

    def test_step_instantiation(self):
        cfg = HumanApprovalConfig(title="Review")
        step = HumanApprovalWorkflowStep(name="HumanReview", approval_config=cfg)
        assert step.name == "HumanReview"


class TestAuditEmitConfig:
    def test_defaults(self):
        cfg = AuditEmitConfig(event_type="bid.evaluated")
        assert cfg.severity == "INFO"
        assert cfg.retention_days == 2555
        assert cfg.pii_fields == []

    def test_step_instantiation(self):
        cfg = AuditEmitConfig(event_type="test.event", severity="WARN", tags=["test"])
        step = AuditEmitWorkflowStep(name="AuditStep", audit_config=cfg)
        assert step.audit_config.severity == "WARN"


class TestComplianceCheckConfig:
    def test_defaults(self):
        cfg = ComplianceCheckConfig(ruleset="./rulesets/default.yaml")
        assert cfg.confidence_threshold == 0.85
        assert cfg.jurisdiction == []

    def test_step_instantiation(self):
        cfg = ComplianceCheckConfig(ruleset="./r.yaml", jurisdiction=["UAE"])
        step = ComplianceCheckWorkflowStep(name="Check", compliance_config=cfg)
        assert step.compliance_config.jurisdiction == ["UAE"]


class TestEdgeModelCallConfig:
    def test_defaults(self):
        cfg = EdgeModelCallConfig(model_id="bitnet-v2", prompt="classify: {{data}}")
        assert cfg.max_tokens == 512
        assert cfg.device_check is True
        assert cfg.offline_only is False

    def test_step_instantiation(self):
        cfg = EdgeModelCallConfig(model_id="m", prompt="p")
        step = EdgeModelCallWorkflowStep(name="EdgeStep", edge_config=cfg)
        assert step.edge_config.model_id == "m"


class TestWorkflowBuilderMetaStep:
    def test_defaults(self):
        cfg = WorkflowBuilderMetaConfig()
        assert cfg.generated_by == "ruvon-workflow-builder/0.1"
        assert cfg.human_reviewed is False

    def test_with_prompt(self):
        cfg = WorkflowBuilderMetaConfig(original_prompt="handle bids", pipeline_version="0.2.0")
        step = WorkflowBuilderMetaStep(name="_meta", meta_config=cfg)
        assert step.meta_config.original_prompt == "handle bids"


# ---------------------------------------------------------------------------
# Builder round-trip tests
# ---------------------------------------------------------------------------

class TestBuilderParsing:
    """Test that WorkflowBuilder correctly parses new step types from YAML dicts."""

    def _make_registry(self):
        return {}

    def test_ai_llm_inference_parsing(self):
        steps_config = [{
            "name": "LLMStep",
            "type": "AI_LLM_INFERENCE",
            "llm_config": {
                "model": "claude-sonnet-4-6",
                "system_prompt": "You are helpful",
                "user_prompt": "Analyse this",
            },
            "automate_next": True,
        }]
        steps = WorkflowBuilder._build_steps_from_config(steps_config)
        assert len(steps) == 1
        assert isinstance(steps[0], AILLMInferenceWorkflowStep)
        assert steps[0].llm_config.model == "claude-sonnet-4-6"

    def test_human_approval_parsing(self):
        steps_config = [{
            "name": "ApprovalStep",
            "type": "HUMAN_APPROVAL",
            "approval_config": {
                "title": "Review",
                "approvers": ["role:admin"],
                "timeout_hours": 48,
            },
        }]
        steps = WorkflowBuilder._build_steps_from_config(steps_config)
        assert len(steps) == 1
        assert isinstance(steps[0], HumanApprovalWorkflowStep)
        assert steps[0].approval_config.timeout_hours == 48

    def test_audit_emit_parsing(self):
        steps_config = [{
            "name": "AuditLog",
            "type": "AUDIT_EMIT",
            "audit_config": {
                "event_type": "bid.evaluated",
                "severity": "CRITICAL",
            },
        }]
        steps = WorkflowBuilder._build_steps_from_config(steps_config)
        assert isinstance(steps[0], AuditEmitWorkflowStep)
        assert steps[0].audit_config.severity == "CRITICAL"

    def test_compliance_check_parsing(self):
        steps_config = [{
            "name": "Compliance",
            "type": "COMPLIANCE_CHECK",
            "compliance_config": {"ruleset": "./rules.yaml"},
        }]
        steps = WorkflowBuilder._build_steps_from_config(steps_config)
        assert isinstance(steps[0], ComplianceCheckWorkflowStep)

    def test_edge_model_call_parsing(self):
        steps_config = [{
            "name": "EdgeClassify",
            "type": "EDGE_MODEL_CALL",
            "edge_config": {"model_id": "bitnet-v2", "prompt": "classify"},
        }]
        steps = WorkflowBuilder._build_steps_from_config(steps_config)
        assert isinstance(steps[0], EdgeModelCallWorkflowStep)

    def test_workflow_builder_meta_parsing(self):
        steps_config = [{
            "name": "_meta",
            "type": "WORKFLOW_BUILDER_META",
            "meta_config": {"original_prompt": "test prompt"},
        }]
        steps = WorkflowBuilder._build_steps_from_config(steps_config)
        assert isinstance(steps[0], WorkflowBuilderMetaStep)
        assert steps[0].meta_config.original_prompt == "test prompt"

    def test_unknown_type_still_raises(self):
        steps_config = [{"name": "Bad", "type": "NOT_A_REAL_TYPE_XYZ", "function": "some.func"}]
        with pytest.raises(ValueError, match="Unknown step type"):
            WorkflowBuilder._build_steps_from_config(steps_config)


# ---------------------------------------------------------------------------
# Workflow execution tests
# ---------------------------------------------------------------------------

class SimpleState(BaseModel):
    result: str = ""
    audit_emitted: bool = False
    llm_result: str = ""
    passed: bool = False
    score: float = 0.0
    violations: list = []
    edge_result: str = ""


def _make_workflow(steps, state=None):
    """Create a minimal Workflow with mocked providers."""
    from ruvon.workflow import Workflow
    from ruvon.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine

    persistence = AsyncMock()
    persistence.save_workflow = AsyncMock()
    persistence.log_audit_event = AsyncMock()
    execution = AsyncMock()
    observer = AsyncMock()
    builder = MagicMock()
    builder.template_engine_cls = Jinja2TemplateEngine

    workflow = Workflow(
        workflow_id="test-wf-001",
        workflow_steps=steps,
        initial_state_model=state or SimpleState(),
        workflow_type="TestWorkflow",
        persistence_provider=persistence,
        execution_provider=execution,
        workflow_observer=observer,
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    return workflow, persistence


@pytest.mark.asyncio
async def test_human_approval_pauses_on_first_call():
    cfg = HumanApprovalConfig(title="Review")
    step = HumanApprovalWorkflowStep(name="Approve", approval_config=cfg)
    workflow, _ = _make_workflow([step])

    with pytest.raises(WorkflowPauseDirective) as exc_info:
        await workflow.next_step(user_input={})

    assert "approval_config" in exc_info.value.result


@pytest.mark.asyncio
async def test_human_approval_resumes_with_input():
    cfg = HumanApprovalConfig(title="Review")
    step = HumanApprovalWorkflowStep(name="Approve", approval_config=cfg)
    state = SimpleState()
    workflow, _ = _make_workflow([step], state)

    # Set status to WAITING_HUMAN so next_step() knows we are resuming
    workflow.status = "WAITING_HUMAN"
    await workflow.next_step(user_input={"llm_result": "approved"})
    # The step should complete — workflow moves past the human approval step
    assert workflow.status == "COMPLETED"


@pytest.mark.asyncio
async def test_audit_emit_calls_persistence():
    cfg = AuditEmitConfig(event_type="test.audit", severity="INFO")
    step = AuditEmitWorkflowStep(name="Audit", audit_config=cfg)
    workflow, persistence = _make_workflow([step])

    await workflow.next_step(user_input={})

    # log_audit_event may be called multiple times (step + workflow completion)
    assert persistence.log_audit_event.called
    # Verify the step-specific call was made with the correct event_type
    step_calls = [
        c for c in persistence.log_audit_event.call_args_list
        if c.kwargs.get("event_type") == "test.audit"
    ]
    assert len(step_calls) == 1


@pytest.mark.asyncio
async def test_workflow_builder_meta_noop():
    cfg = WorkflowBuilderMetaConfig(original_prompt="test")
    step = WorkflowBuilderMetaStep(name="_meta", meta_config=cfg)
    workflow, _ = _make_workflow([step])

    await workflow.next_step(user_input={})
    # The meta step is a no-op at runtime; workflow should complete without error
    assert workflow.status == "COMPLETED"


@pytest.mark.asyncio
async def test_ai_llm_inference_cloud_path():
    cfg = AILLMInferenceConfig(
        model="claude-sonnet-4-6",
        model_location="cloud",
        system_prompt="You are helpful",
        user_prompt="Hello",
    )
    step = AILLMInferenceWorkflowStep(name="LLMStep", llm_config=cfg)
    workflow, _ = _make_workflow([step])

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="mocked response")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client

    import sys
    with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}):
        await workflow.next_step(user_input={})

    state_dict = workflow.state.model_dump()
    assert state_dict.get("llm_result") == "mocked response"


@pytest.mark.asyncio
async def test_ai_llm_inference_ollama_path():
    cfg = AILLMInferenceConfig(
        model="llama3",
        model_location="ollama",
        system_prompt="You are helpful",
        user_prompt="Hello",
        ollama_base_url="http://localhost:11434",
    )
    step = AILLMInferenceWorkflowStep(name="OllamaStep", llm_config=cfg)
    workflow, _ = _make_workflow([step])

    import httpx
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"message": {"content": "ollama response"}}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_http
        await workflow.next_step(user_input={})

    state_dict = workflow.state.model_dump()
    assert state_dict.get("llm_result") == "ollama response"


@pytest.mark.asyncio
async def test_compliance_check_with_ruleset(tmp_path):
    ruleset_file = tmp_path / "rules.yaml"
    ruleset_file.write_text(
        "rules:\n"
        "  - id: R001\n"
        "    condition: 'True'\n"
        "    message: Always passes\n"
        "  - id: R002\n"
        "    condition: 'False'\n"
        "    message: Always fails\n"
    )
    cfg = ComplianceCheckConfig(ruleset=str(ruleset_file))
    step = ComplianceCheckWorkflowStep(name="Check", compliance_config=cfg)
    workflow, _ = _make_workflow([step])

    await workflow.next_step(user_input={})
    state_dict = workflow.state.model_dump()
    assert state_dict.get("passed") is False
    assert state_dict.get("score") == 0.5
    assert len(state_dict.get("violations", [])) == 1


@pytest.mark.asyncio
async def test_compliance_check_ruleset_not_found():
    from ruvon.models import WorkflowFailedException
    cfg = ComplianceCheckConfig(ruleset="/nonexistent/rules.yaml")
    step = ComplianceCheckWorkflowStep(name="Check", compliance_config=cfg)
    workflow, _ = _make_workflow([step])

    with pytest.raises(WorkflowFailedException) as exc_info:
        await workflow.next_step(user_input={})
    assert "Compliance ruleset not found" in str(exc_info.value.original_exception)


@pytest.mark.asyncio
async def test_edge_model_call_requires_inference_provider():
    from ruvon.models import WorkflowFailedException
    cfg = EdgeModelCallConfig(model_id="bitnet-v2", prompt="classify")
    step = EdgeModelCallWorkflowStep(name="Edge", edge_config=cfg)
    workflow, _ = _make_workflow([step])
    workflow.inference_provider = None

    with pytest.raises(WorkflowFailedException) as exc_info:
        await workflow.next_step(user_input={})
    assert "InferenceProvider is not configured" in str(exc_info.value.original_exception)
