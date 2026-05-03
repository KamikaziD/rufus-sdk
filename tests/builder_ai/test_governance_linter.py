"""Tests for the deterministic GOV-001..GOV-007 governance rules.

No LLM calls required — the linter is fully deterministic.
"""

import pytest
from ruvon.builder_ai.stages.governance_linter import GovernanceLinter


def _linter():
    return GovernanceLinter()


def _workflow(steps, extra=None):
    base = {"name": "test", "version": "1.0", "owner": "test-team", "steps": steps}
    if extra:
        base.update(extra)
    return base


# ---------------------------------------------------------------------------
# GOV-001: PII audit trail
# ---------------------------------------------------------------------------

class TestGOV001:
    def test_pass_no_pii_steps(self):
        wf = _workflow([{"name": "S1", "type": "STANDARD"}])
        result = _linter().lint(wf).results[0]
        assert result.rule_id == "GOV-001"
        assert result.passed

    def test_pass_pii_with_audit_downstream(self):
        wf = _workflow([
            {"name": "LLM", "type": "AI_LLM_INFERENCE", "llm_config": {"pii_detected": True}},
            {"name": "Audit", "type": "AUDIT_EMIT", "audit_config": {}},
        ])
        result = _linter().lint(wf).results[0]
        assert result.rule_id == "GOV-001"
        assert result.passed

    def test_fail_pii_without_audit(self):
        wf = _workflow([
            {"name": "LLM", "type": "AI_LLM_INFERENCE", "llm_config": {"pii_detected": True}},
            {"name": "Notify", "type": "STANDARD"},
        ])
        result = _linter().lint(wf).results[0]
        assert result.rule_id == "GOV-001"
        assert not result.passed
        assert result.severity == "ERROR"

    def test_pass_pii_false(self):
        wf = _workflow([
            {"name": "LLM", "type": "AI_LLM_INFERENCE", "llm_config": {"pii_detected": False}},
        ])
        result = _linter().lint(wf).results[0]
        assert result.passed


# ---------------------------------------------------------------------------
# GOV-002: High-risk approval gate
# ---------------------------------------------------------------------------

class TestGOV002:
    def test_pass_no_compliance_steps(self):
        wf = _workflow([{"name": "S1", "type": "STANDARD"}])
        result = _linter().lint(wf).results[1]
        assert result.rule_id == "GOV-002"
        assert result.passed

    def test_pass_compliance_with_approval(self):
        wf = _workflow([
            {"name": "Check", "type": "COMPLIANCE_CHECK", "compliance_config": {}},
            {"name": "Approve", "type": "HUMAN_APPROVAL", "approval_config": {}},
            {"name": "Notify", "type": "STANDARD"},
        ])
        result = _linter().lint(wf).results[1]
        assert result.passed

    def test_fail_compliance_without_approval(self):
        wf = _workflow([
            {"name": "Check", "type": "COMPLIANCE_CHECK", "compliance_config": {}},
            {"name": "Notify", "type": "STANDARD"},
            {"name": "Send", "type": "HTTP", "http_config": {}},
        ])
        result = _linter().lint(wf).results[1]
        assert not result.passed
        assert result.severity == "ERROR"


# ---------------------------------------------------------------------------
# GOV-003: HTTP retry config
# ---------------------------------------------------------------------------

class TestGOV003:
    def test_pass_no_http_steps(self):
        wf = _workflow([{"name": "S1", "type": "STANDARD"}])
        result = _linter().lint(wf).results[2]
        assert result.rule_id == "GOV-003"
        assert result.passed

    def test_pass_http_with_retry(self):
        wf = _workflow([
            {"name": "Call", "type": "HTTP", "http_config": {"url": "http://x", "retry": {"max": 3}}},
        ])
        result = _linter().lint(wf).results[2]
        assert result.passed

    def test_warn_http_without_retry(self):
        wf = _workflow([
            {"name": "Call", "type": "HTTP", "http_config": {"url": "http://x"}},
        ])
        result = _linter().lint(wf).results[2]
        assert not result.passed
        assert result.severity == "WARN"


# ---------------------------------------------------------------------------
# GOV-004: No human gate
# ---------------------------------------------------------------------------

class TestGOV004:
    def test_pass_with_human_approval(self):
        wf = _workflow([
            {"name": "Approve", "type": "HUMAN_APPROVAL", "approval_config": {"title": "t"}},
        ])
        result = _linter().lint(wf).results[3]
        assert result.rule_id == "GOV-004"
        assert result.passed

    def test_pass_with_human_in_loop(self):
        wf = _workflow([
            {"name": "HITL", "type": "HUMAN_IN_LOOP"},
        ])
        result = _linter().lint(wf).results[3]
        assert result.passed

    def test_warn_no_human_gate(self):
        wf = _workflow([
            {"name": "Auto1", "type": "STANDARD"},
            {"name": "Auto2", "type": "AI_LLM_INFERENCE", "llm_config": {}},
        ])
        result = _linter().lint(wf).results[3]
        assert not result.passed
        assert result.severity == "WARN"


# ---------------------------------------------------------------------------
# GOV-005: Edge model availability
# ---------------------------------------------------------------------------

class TestGOV005:
    def test_pass_no_edge_steps(self):
        wf = _workflow([{"name": "S1", "type": "STANDARD"}])
        result = _linter().lint(wf).results[4]
        assert result.rule_id == "GOV-005"
        assert result.passed

    def test_info_edge_steps_present(self):
        wf = _workflow([
            {"name": "EdgeCall", "type": "EDGE_MODEL_CALL", "edge_config": {"model_id": "m", "prompt": "p"}},
        ])
        result = _linter().lint(wf).results[4]
        assert not result.passed
        assert result.severity == "INFO"
        assert "EdgeCall" in result.message


# ---------------------------------------------------------------------------
# GOV-006: Data sovereignty tag
# ---------------------------------------------------------------------------

class TestGOV006:
    def test_pass_no_external_steps(self):
        wf = _workflow([{"name": "S1", "type": "STANDARD"}])
        result = _linter().lint(wf).results[5]
        assert result.rule_id == "GOV-006"
        assert result.passed

    def test_pass_llm_with_sovereignty_tag(self):
        wf = _workflow([
            {"name": "LLM", "type": "AI_LLM_INFERENCE", "llm_config": {"data_sovereignty": "cloud"}},
        ])
        result = _linter().lint(wf).results[5]
        assert result.passed

    def test_fail_llm_without_sovereignty_tag(self):
        wf = _workflow([
            {"name": "LLM", "type": "AI_LLM_INFERENCE", "llm_config": {"model": "claude-sonnet-4-6"}},
        ])
        result = _linter().lint(wf).results[5]
        assert not result.passed
        assert result.severity == "ERROR"


# ---------------------------------------------------------------------------
# GOV-007: Version and owner metadata
# ---------------------------------------------------------------------------

class TestGOV007:
    def test_pass_both_present(self):
        wf = _workflow([{"name": "S1", "type": "STANDARD"}])
        result = _linter().lint(wf).results[6]
        assert result.rule_id == "GOV-007"
        assert result.passed

    def test_warn_missing_version(self):
        wf = {"name": "test", "owner": "team", "steps": [{"name": "S1", "type": "STANDARD"}]}
        result = _linter().lint(wf).results[6]
        assert not result.passed

    def test_warn_missing_owner(self):
        wf = {"name": "test", "version": "1.0", "steps": [{"name": "S1", "type": "STANDARD"}]}
        result = _linter().lint(wf).results[6]
        assert not result.passed

    def test_warn_missing_both(self):
        wf = {"name": "test", "steps": [{"name": "S1", "type": "STANDARD"}]}
        result = _linter().lint(wf).results[6]
        assert not result.passed
        assert "version" in result.message
        assert "owner" in result.message


# ---------------------------------------------------------------------------
# LintReport summary
# ---------------------------------------------------------------------------

class TestLintReport:
    def test_summary_counts(self):
        wf = _workflow([
            {"name": "S1", "type": "STANDARD"},
        ], extra={"owner": "team"})
        report = _linter().lint(wf)
        summary = report.summary()
        assert "rules passed" in summary

    def test_has_errors_property(self):
        # GOV-001 ERROR: PII without audit
        wf = _workflow([
            {"name": "LLM", "type": "AI_LLM_INFERENCE", "llm_config": {"pii_detected": True}},
        ])
        report = _linter().lint(wf)
        assert report.has_errors
