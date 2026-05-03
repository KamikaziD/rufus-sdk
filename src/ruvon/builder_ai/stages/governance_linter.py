"""Stage 6 — Governance Linter: deterministic GOV-001..GOV-007 rule evaluation."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from ruvon.builder_ai.models import LintReport, LintResult

logger = logging.getLogger(__name__)


def _step_ids_downstream(step_name: str, edges: List[Dict]) -> Set[str]:
    """Return the set of all step names reachable downstream from step_name via edges."""
    visited: Set[str] = set()
    queue = [step_name]
    while queue:
        current = queue.pop()
        for edge in edges:
            if edge.get("from_step") == current or edge.get("from") == current:
                target = edge.get("to_step") or edge.get("to", "")
                if target and target not in visited:
                    visited.add(target)
                    queue.append(target)
    return visited


def _steps_by_type(steps: List[Dict], step_type: str) -> List[Dict]:
    return [s for s in steps if s.get("type", "").upper() == step_type.upper()]


def _has_step_type(steps: List[Dict], step_type: str) -> bool:
    return any(s.get("type", "").upper() == step_type.upper() for s in steps)


class GovernanceLinter:
    """Stage 6: Apply GOV-001..GOV-007 governance rules to a generated workflow dict."""

    def lint(self, workflow: Dict[str, Any]) -> LintReport:
        steps: List[Dict] = workflow.get("steps", [])
        # edges can be top-level or absent (sequential implied)
        edges: List[Dict] = workflow.get("edges", [])
        results = [
            self._gov001_pii_audit(steps, edges),
            self._gov002_high_risk_approval(steps, edges),
            self._gov003_http_retry(steps),
            self._gov004_no_human_gate(steps),
            self._gov005_edge_model_availability(steps),
            self._gov006_data_sovereignty_tag(steps),
            self._gov007_version_owner_metadata(workflow),
        ]
        report = LintReport(results=results)
        logger.debug("[Stage 6] Lint complete: %s", report.summary())
        return report

    def _gov001_pii_audit(self, steps: List[Dict], edges: List[Dict]) -> LintResult:
        """AI steps with pii_detected=true must have AUDIT_EMIT downstream."""
        violations = []
        for step in steps:
            if step.get("type", "").upper() != "AI_LLM_INFERENCE":
                continue
            cfg = step.get("llm_config", {})
            if not cfg.get("pii_detected", False):
                continue
            step_name = step.get("name", "")
            downstream = _step_ids_downstream(step_name, edges)
            all_names = [s.get("name", "") for s in steps]
            # If no edges defined, check sequentially
            if not edges:
                idx = next((i for i, s in enumerate(steps) if s.get("name") == step_name), -1)
                downstream = {s.get("name", "") for s in steps[idx + 1:]}
            has_audit = any(
                s.get("name") in downstream and s.get("type", "").upper() == "AUDIT_EMIT"
                for s in steps
            ) or any(
                s.get("type", "").upper() == "AUDIT_EMIT" and s.get("name") in downstream
                for s in steps
            )
            if not has_audit:
                violations.append(step_name)
        if violations:
            return LintResult(
                rule_id="GOV-001",
                severity="ERROR",
                message=f"AI steps with pii_detected=true must have AUDIT_EMIT downstream: {violations}",
                passed=False,
            )
        return LintResult(rule_id="GOV-001", severity="ERROR", message="PII audit trail check passed", passed=True)

    def _gov002_high_risk_approval(self, steps: List[Dict], edges: List[Dict]) -> LintResult:
        """Compliance check violations should route to HUMAN_APPROVAL before action steps."""
        compliance_steps = _steps_by_type(steps, "COMPLIANCE_CHECK")
        if not compliance_steps:
            return LintResult(rule_id="GOV-002", severity="ERROR", message="No compliance check steps found (skipped)", passed=True)

        has_approval = _has_step_type(steps, "HUMAN_APPROVAL") or _has_step_type(steps, "HUMAN_IN_LOOP")
        if not has_approval and len(steps) > 2:
            return LintResult(
                rule_id="GOV-002",
                severity="ERROR",
                message="Workflow has COMPLIANCE_CHECK but no HUMAN_APPROVAL gate before action steps",
                passed=False,
            )
        return LintResult(rule_id="GOV-002", severity="ERROR", message="Human approval gate present for high-risk decisions", passed=True)

    def _gov003_http_retry(self, steps: List[Dict]) -> LintResult:
        """HTTP steps should have retry configuration."""
        violations = []
        for step in _steps_by_type(steps, "HTTP"):
            cfg = step.get("http_config", {})
            if not cfg.get("retry") and not cfg.get("max_retries"):
                violations.append(step.get("name", ""))
        if violations:
            return LintResult(
                rule_id="GOV-003",
                severity="WARN",
                message=f"HTTP steps missing retry configuration: {violations}",
                passed=False,
            )
        return LintResult(rule_id="GOV-003", severity="WARN", message="HTTP retry configuration check passed", passed=True)

    def _gov004_no_human_gate(self, steps: List[Dict]) -> LintResult:
        """Fully automated workflows (no human gate) should be noted."""
        has_human = (
            _has_step_type(steps, "HUMAN_APPROVAL")
            or _has_step_type(steps, "HUMAN_IN_LOOP")
        )
        if not has_human:
            return LintResult(
                rule_id="GOV-004",
                severity="WARN",
                message="Workflow has no human gate — consider adding HUMAN_APPROVAL for irreversible actions",
                passed=False,
            )
        return LintResult(rule_id="GOV-004", severity="WARN", message="Human gate present", passed=True)

    def _gov005_edge_model_availability(self, steps: List[Dict]) -> LintResult:
        """Edge model steps — flag for device availability confirmation."""
        edge_steps = _steps_by_type(steps, "EDGE_MODEL_CALL")
        if edge_steps:
            names = [s.get("name", "") for s in edge_steps]
            return LintResult(
                rule_id="GOV-005",
                severity="INFO",
                message=f"EDGE_MODEL_CALL steps detected {names} — confirm local models are deployed on target devices",
                passed=False,
            )
        return LintResult(rule_id="GOV-005", severity="INFO", message="No edge model steps (skipped)", passed=True)

    def _gov006_data_sovereignty_tag(self, steps: List[Dict]) -> LintResult:
        """Steps writing to external systems need a data_sovereignty tag."""
        violations = []
        for step in steps:
            step_type = step.get("type", "").upper()
            if step_type in ("HTTP", "AI_LLM_INFERENCE"):
                cfg = step.get("llm_config", step.get("http_config", {}))
                if not cfg.get("data_sovereignty"):
                    violations.append(step.get("name", ""))
        if violations:
            return LintResult(
                rule_id="GOV-006",
                severity="ERROR",
                message=f"Steps writing to external systems missing data_sovereignty tag: {violations}",
                passed=False,
            )
        return LintResult(rule_id="GOV-006", severity="ERROR", message="Data sovereignty tags present", passed=True)

    def _gov007_version_owner_metadata(self, workflow: Dict[str, Any]) -> LintResult:
        """Workflow should declare version and owner."""
        missing = []
        if not workflow.get("version"):
            missing.append("version")
        if not workflow.get("owner"):
            missing.append("owner")
        if missing:
            return LintResult(
                rule_id="GOV-007",
                severity="WARN",
                message=f"Workflow missing metadata fields: {missing}",
                passed=False,
            )
        return LintResult(rule_id="GOV-007", severity="WARN", message="Version and owner metadata present", passed=True)
