"""Tests for the deterministic SchemaValidator (Stage 5)."""

import pytest
from ruvon.builder_ai.stages.schema_validator import SchemaValidator


def _validator():
    return SchemaValidator()


class TestSchemaValidator:
    def test_valid_minimal_workflow(self):
        wf = {"name": "test", "version": "1.0", "steps": [{"name": "S1", "type": "STANDARD", "function": "some.func"}]}
        validated, errors = _validator().validate(wf)
        assert errors == []

    def test_missing_steps_key(self):
        wf = {"name": "test"}
        _, errors = _validator().validate(wf)
        assert any("steps" in e for e in errors)

    def test_empty_steps_list(self):
        wf = {"name": "test", "steps": []}
        _, errors = _validator().validate(wf)
        assert any("at least one step" in e for e in errors)

    def test_unknown_step_type(self):
        wf = {"name": "test", "steps": [{"name": "S1", "type": "NOT_REAL_XYZ"}]}
        _, errors = _validator().validate(wf)
        assert any("NOT_REAL_XYZ" in e for e in errors)

    def test_auto_repair_missing_name(self):
        wf = {"steps": [{"name": "S1", "type": "STANDARD", "function": "some.func"}]}
        validated, errors = _validator().validate(wf)
        assert validated.get("name") == "generated-workflow"

    def test_auto_repair_missing_version(self):
        wf = {"name": "test", "steps": [{"name": "S1", "type": "STANDARD", "function": "some.func"}]}
        validated, errors = _validator().validate(wf)
        assert validated.get("version") == "1.0"

    def test_duplicate_step_names(self):
        wf = {"name": "test", "steps": [
            {"name": "S1", "type": "STANDARD", "function": "f"},
            {"name": "S1", "type": "STANDARD", "function": "f"},
        ]}
        _, errors = _validator().validate(wf)
        assert any("Duplicate" in e for e in errors)

    def test_ai_llm_missing_required_config(self):
        wf = {"name": "test", "steps": [{"name": "LLM", "type": "AI_LLM_INFERENCE", "llm_config": {}}]}
        _, errors = _validator().validate(wf)
        # Must require model, system_prompt, user_prompt
        assert any("model" in e or "system_prompt" in e or "user_prompt" in e for e in errors)

    def test_ai_llm_valid_config(self):
        wf = {"name": "test", "steps": [{
            "name": "LLM",
            "type": "AI_LLM_INFERENCE",
            "llm_config": {"model": "claude-sonnet-4-6", "system_prompt": "s", "user_prompt": "u"},
        }]}
        _, errors = _validator().validate(wf)
        assert errors == []

    def test_human_approval_missing_title(self):
        wf = {"name": "test", "steps": [{"name": "A", "type": "HUMAN_APPROVAL", "approval_config": {}}]}
        _, errors = _validator().validate(wf)
        assert any("title" in e for e in errors)

    def test_audit_emit_missing_event_type(self):
        wf = {"name": "test", "steps": [{"name": "A", "type": "AUDIT_EMIT", "audit_config": {}}]}
        _, errors = _validator().validate(wf)
        assert any("event_type" in e for e in errors)

    def test_compliance_check_missing_ruleset(self):
        wf = {"name": "test", "steps": [{"name": "C", "type": "COMPLIANCE_CHECK", "compliance_config": {}}]}
        _, errors = _validator().validate(wf)
        assert any("ruleset" in e for e in errors)

    def test_edge_model_call_missing_fields(self):
        wf = {"name": "test", "steps": [{"name": "E", "type": "EDGE_MODEL_CALL", "edge_config": {}}]}
        _, errors = _validator().validate(wf)
        assert any("model_id" in e or "prompt" in e for e in errors)

    def test_standard_auto_repair_function(self):
        wf = {"name": "test", "steps": [{"name": "S1", "type": "STANDARD"}]}
        validated, errors = _validator().validate(wf)
        # Should auto-repair with placeholder function
        assert validated["steps"][0].get("function") == "ruvon_workflows.steps.identity"

    def test_workflow_builder_meta_no_required_fields(self):
        # workflow_builder_meta has no required config fields
        wf = {"name": "test", "steps": [{"name": "_meta", "type": "WORKFLOW_BUILDER_META", "meta_config": {}}]}
        _, errors = _validator().validate(wf)
        assert errors == []

    def test_type_normalised_to_uppercase(self):
        wf = {"name": "test", "steps": [{"name": "S1", "type": "standard", "function": "some.func"}]}
        validated, errors = _validator().validate(wf)
        assert validated["steps"][0]["type"] == "STANDARD"
