"""Sidecar Step 5 — Apply approved configuration change.

Applies an operator-approved performance suggestion to the device config.
Decides between two application paths:
  - HOT-SWAP:       config-only changes (fraud thresholds, floor limits)
                    Reloads config without stopping the agent.
  - DRAIN+RESTART:  structural changes (executor, DB schema, workflow YAML)
                    Drains in-flight transactions then restarts.

This module is also compiled to WASM for sandboxed execution via Ruvon's
WASM step type. When running as WASM, it reads the proposal from stdin
and writes the result to stdout.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Keys that can be hot-swapped without restart
_HOT_SWAP_KEYS = {
    "fraud_threshold",
    "floor_limit",
    "max_retry_count",
    "saf_sync_interval_seconds",
    "http_timeout_seconds",
    "log_level",
    "max_concurrent_workflows",
    "heartbeat_interval_seconds",
}

# Keys that require drain+restart
_RESTART_REQUIRED_KEYS = {
    "execution_provider",
    "persistence_provider",
    "db_path",
    "workflow_registry",
    "uvloop_enabled",
}

_CONFIG_PATH = os.environ.get("RUVON_EDGE_CONFIG_PATH", "config/edge_device.yaml")
_CONFIG_BACKUP_SUFFIX = ".pre_sidecar_backup"


def apply_config_change(state: Any, context: Any, **kwargs) -> Dict[str, Any]:
    """Ruvon step function: apply an approved config change.

    Reads state.suggestion (set by GenerateSuggestions step).
    Reads state.approved (set by ApprovalGate HITL step).

    Returns dict with apply_outcome key.
    """
    if not getattr(state, "approved", False):
        logger.info("[Sidecar] Change was not approved; skipping apply.")
        return {"apply_outcome": "skipped_not_approved"}

    suggestion = getattr(state, "suggestion", {})
    if not suggestion:
        logger.warning("[Sidecar] No suggestion to apply.")
        return {"apply_outcome": "skipped_no_suggestion"}

    change_key = suggestion.get("change", {}).get("key", "")
    change_value = suggestion.get("change", {}).get("value")

    if change_key in _HOT_SWAP_KEYS:
        outcome = _apply_hot_swap(change_key, change_value)
    elif change_key in _RESTART_REQUIRED_KEYS:
        outcome = _apply_drain_and_restart(change_key, change_value)
    else:
        logger.warning(
            "[Sidecar] Unknown config key '%s'; applying as hot-swap cautiously.", change_key
        )
        outcome = _apply_hot_swap(change_key, change_value)

    logger.info("[Sidecar] Apply outcome: %s", outcome)
    return {"apply_outcome": outcome}


def _apply_hot_swap(key: str, value: Any) -> str:
    """Write config change and signal agent to reload without restart."""
    try:
        _update_config_file(key, value)
        # Send SIGHUP to the edge agent process to trigger config reload
        agent_pid = _find_agent_pid()
        if agent_pid:
            os.kill(agent_pid, signal.SIGHUP)
            logger.info("[Sidecar] Sent SIGHUP to agent PID %d for hot-swap", agent_pid)
        else:
            logger.warning("[Sidecar] Agent PID not found; config file updated but reload not signaled")
        return f"hot_swapped:{key}={value}"
    except Exception as e:
        logger.error("[Sidecar] Hot-swap failed: %s", e)
        return f"failed:{e}"


def _apply_drain_and_restart(key: str, value: Any) -> str:
    """Drain in-flight workflows, apply change, then restart the edge agent."""
    try:
        drain_timeout = int(os.environ.get("RUVON_SIDECAR_DRAIN_TIMEOUT", "30"))
        logger.info("[Sidecar] Draining workflows before restart (timeout=%ds)...", drain_timeout)

        # Wait for active workflows to complete (poll DB)
        deadline = time.time() + drain_timeout
        while time.time() < deadline:
            active = _count_active_workflows()
            if active == 0:
                logger.info("[Sidecar] Drain complete: no active workflows")
                break
            logger.debug("[Sidecar] Waiting for %d active workflows to finish...", active)
            time.sleep(2)

        _update_config_file(key, value)
        logger.info("[Sidecar] Config updated; scheduling restart...")

        # Restart by sending SIGTERM to the agent (systemd/supervisor will restart it)
        agent_pid = _find_agent_pid()
        if agent_pid and agent_pid != os.getpid():
            os.kill(agent_pid, signal.SIGTERM)
            return f"drain_restart:{key}={value}"

        return f"config_updated:{key}={value} (manual restart required)"
    except Exception as e:
        logger.error("[Sidecar] Drain+restart failed: %s", e)
        return f"failed:{e}"


def _update_config_file(key: str, value: Any) -> None:
    """Update the edge device config file with the new key=value.

    Writes a backup alongside the config file before overwriting so
    rollback_change() can restore it if ApplyChange fails.
    """
    import yaml

    config_path = Path(_CONFIG_PATH)
    if not config_path.exists():
        logger.warning("[Sidecar] Config file not found at %s; creating", config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config = {}
    else:
        # Write backup before modifying
        backup_path = str(config_path) + _CONFIG_BACKUP_SUFFIX
        shutil.copy2(config_path, backup_path)
        config = yaml.safe_load(config_path.read_text()) or {}

    # Support nested keys with dot notation: "sync.interval" → config["sync"]["interval"]
    parts = key.split(".")
    target = config
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value

    config_path.write_text(yaml.dump(config, default_flow_style=False, allow_unicode=True))
    logger.info("[Sidecar] Config updated: %s = %s", key, value)


def _find_agent_pid() -> Optional[int]:
    """Find the PID of the running RuvonEdgeAgent process."""
    pid_file = os.environ.get("RUVON_EDGE_PID_FILE", "edge_agent.pid")
    try:
        from pathlib import Path
        pid_path = Path(pid_file)
        if pid_path.exists():
            return int(pid_path.read_text().strip())
    except Exception:
        pass
    return None


def _count_active_workflows() -> int:
    """Count workflows currently in RUNNING state."""
    db_path = os.environ.get("RUVON_EDGE_DB_PATH", "edge_workflows.db")
    try:
        import sqlite3
        con = sqlite3.connect(db_path, timeout=2.0)
        count = con.execute(
            "SELECT COUNT(*) FROM workflow_executions WHERE status = 'RUNNING'"
        ).fetchone()[0]
        con.close()
        return count
    except Exception:
        return 0


# Public alias used by deployment_monitor.yaml step function reference
apply_approved_change = apply_config_change


# ---------------------------------------------------------------------------
# Saga compensate function — restore config from backup if ApplyChange fails
# ---------------------------------------------------------------------------

def rollback_change(state: Any, context: Any, **kwargs) -> Dict[str, Any]:
    """Saga compensate function: restore config from backup if ApplyChange fails.

    Called automatically by the Saga pattern when ApplyChange raises an exception.
    Looks for a backup file written by _update_config_file before the change.
    """
    backup_path = getattr(state, "config_backup_path", None)
    if not backup_path:
        # Derive backup path from default config location
        config_path = Path(os.environ.get("RUVON_EDGE_CONFIG_PATH", "edge_config.yaml"))
        backup_path = str(config_path) + _CONFIG_BACKUP_SUFFIX

    backup = Path(backup_path)
    if backup.exists():
        config_path = Path(os.environ.get("RUVON_EDGE_CONFIG_PATH", "edge_config.yaml"))
        shutil.copy2(backup, config_path)
        logger.info("[Sidecar:rollback] Config restored from backup: %s → %s", backup_path, config_path)
        return {"rollback_applied": True, "rollback_source": backup_path}

    logger.warning("[Sidecar:rollback] No backup found at %s; rollback skipped", backup_path)
    return {"rollback_applied": False}


# ---------------------------------------------------------------------------
# WASM entry point (when compiled to WASM via Wizer/WASI)
# ---------------------------------------------------------------------------

def wasm_main() -> None:
    """Entry point when running as a WASM binary.

    Reads proposal JSON from stdin, applies change, writes result to stdout.
    """
    try:
        proposal = json.loads(sys.stdin.read())
        key = proposal.get("key", "")
        value = proposal.get("value")
        approved = proposal.get("approved", False)

        if not approved:
            result = {"outcome": "skipped_not_approved"}
        elif key in _HOT_SWAP_KEYS:
            outcome = _apply_hot_swap(key, value)
            result = {"outcome": outcome, "method": "hot_swap"}
        else:
            outcome = _apply_drain_and_restart(key, value)
            result = {"outcome": outcome, "method": "drain_restart"}

        sys.stdout.write(json.dumps(result))
    except Exception as e:
        sys.stdout.write(json.dumps({"outcome": f"error:{e}"}))
        sys.exit(1)


if __name__ == "__main__":
    wasm_main()
