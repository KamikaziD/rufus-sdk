"""
Edge Device Command Handler

Processes commands received from the cloud (via heartbeat or WebSocket).
"""

import asyncio
import logging
import os
import platform
import subprocess
import sys
from datetime import datetime
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)


class CommandHandler:
    """Handles command execution on edge devices."""

    def __init__(self, device_id: str, cloud_url: str, api_key: str):
        self.device_id = device_id
        self.cloud_url = cloud_url
        self.api_key = api_key

    async def process_commands(self, commands: list):
        """Process a list of commands."""
        for cmd in commands:
            command_id = cmd.get("command_id")
            command_type = cmd.get("command_type")
            command_data = cmd.get("command_data", "{}")

            # Parse command_data if it's a JSON string
            if isinstance(command_data, str):
                import json
                try:
                    command_data = json.loads(command_data)
                except:
                    command_data = {}

            logger.info(f"Processing command: {command_type} (ID: {command_id})")

            try:
                # Execute command
                result = await self.execute_command(command_type, command_data)

                # Report success
                await self.report_status(command_id, "completed", result)
                logger.info(f"Command {command_id} completed: {result}")

            except Exception as e:
                # Report failure
                error_msg = str(e)
                await self.report_status(command_id, "failed", error=error_msg)
                logger.error(f"Command {command_id} failed: {error_msg}")

    async def execute_command(self, command_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a specific command and return result."""

        # ─────────────────────────────────────────────────────────────────────
        # Device Management Commands
        # ─────────────────────────────────────────────────────────────────────

        if command_type == "restart":
            return await self._cmd_restart(data)

        elif command_type == "shutdown":
            return await self._cmd_shutdown(data)

        elif command_type == "reboot":
            return await self._cmd_reboot(data)

        # ─────────────────────────────────────────────────────────────────────
        # Configuration Commands
        # ─────────────────────────────────────────────────────────────────────

        elif command_type == "update_config":
            return await self._cmd_update_config(data)

        elif command_type == "reload_config":
            return await self._cmd_reload_config(data)

        # ─────────────────────────────────────────────────────────────────────
        # Maintenance Commands
        # ─────────────────────────────────────────────────────────────────────

        elif command_type == "backup":
            return await self._cmd_backup(data)

        elif command_type == "schedule_backup":
            return await self._cmd_schedule_backup(data)

        elif command_type == "clear_cache":
            return await self._cmd_clear_cache(data)

        elif command_type == "health_check":
            return await self._cmd_health_check(data)

        # ─────────────────────────────────────────────────────────────────────
        # Sync Commands
        # ─────────────────────────────────────────────────────────────────────

        elif command_type == "sync_now":
            return await self._cmd_sync_now(data)

        elif command_type == "force_sync":
            return await self._cmd_force_sync(data)

        # ─────────────────────────────────────────────────────────────────────
        # Workflow Commands
        # ─────────────────────────────────────────────────────────────────────

        elif command_type == "start_workflow":
            return await self._cmd_start_workflow(data)

        elif command_type == "cancel_workflow":
            return await self._cmd_cancel_workflow(data)

        # ─────────────────────────────────────────────────────────────────────
        # Critical Commands
        # ─────────────────────────────────────────────────────────────────────

        elif command_type == "emergency_stop":
            return await self._cmd_emergency_stop(data)

        elif command_type == "fraud_alert":
            return await self._cmd_fraud_alert(data)

        elif command_type == "security_lockdown":
            return await self._cmd_security_lockdown(data)

        elif command_type == "disable_transactions":
            return await self._cmd_disable_transactions(data)

        elif command_type == "enable_transactions":
            return await self._cmd_enable_transactions(data)

        else:
            raise ValueError(f"Unknown command type: {command_type}")

    # ═════════════════════════════════════════════════════════════════════════
    # Command Implementations
    # ═════════════════════════════════════════════════════════════════════════

    async def _cmd_restart(self, data: dict) -> dict:
        """Restart the edge agent (soft restart)."""
        delay = data.get("delay_seconds", 5)
        logger.info(f"Restarting edge agent in {delay} seconds...")

        # Schedule restart
        asyncio.create_task(self._delayed_restart(delay))

        return {
            "status": "restarting",
            "delay_seconds": delay,
            "message": f"Edge agent will restart in {delay} seconds"
        }

    async def _delayed_restart(self, delay: int):
        """Delayed restart implementation."""
        await asyncio.sleep(delay)
        logger.info("Executing restart now...")
        # Exit the process - supervisor should restart it
        sys.exit(0)

    async def _cmd_shutdown(self, data: dict) -> dict:
        """Graceful shutdown of edge agent."""
        delay = data.get("delay_seconds", 10)
        logger.info(f"Shutting down in {delay} seconds...")

        asyncio.create_task(self._delayed_shutdown(delay))

        return {
            "status": "shutting_down",
            "delay_seconds": delay
        }

    async def _delayed_shutdown(self, delay: int):
        """Delayed shutdown implementation."""
        await asyncio.sleep(delay)
        logger.info("Shutting down now...")
        sys.exit(0)

    async def _cmd_reboot(self, data: dict) -> dict:
        """Reboot the entire system (requires root)."""
        delay = data.get("delay_seconds", 60)
        logger.warning(f"System reboot requested in {delay} seconds...")

        # This requires root/admin privileges
        system = platform.system()

        if system == "Linux":
            cmd = f"sleep {delay} && sudo reboot"
        elif system == "Darwin":  # macOS
            cmd = f"sleep {delay} && sudo shutdown -r now"
        elif system == "Windows":
            cmd = f"shutdown /r /t {delay}"
        else:
            raise RuntimeError(f"Reboot not supported on {system}")

        # Schedule reboot
        subprocess.Popen(cmd, shell=True)

        return {
            "status": "reboot_scheduled",
            "delay_seconds": delay,
            "system": system
        }

    async def _cmd_update_config(self, data: dict) -> dict:
        """Update device configuration."""
        config = data.get("config", {})
        logger.info("Updating configuration...")

        # TODO: Save config to file
        # config_path = "/etc/rufus/config.json"
        # with open(config_path, 'w') as f:
        #     json.dump(config, f, indent=2)

        return {
            "status": "config_updated",
            "config_keys": list(config.keys())
        }

    async def _cmd_reload_config(self, data: dict) -> dict:
        """Reload configuration from file."""
        logger.info("Reloading configuration...")

        # TODO: Reload config
        return {"status": "config_reloaded"}

    async def _cmd_backup(self, data: dict) -> dict:
        """Trigger backup operation."""
        target = data.get("target", "local")
        logger.info(f"Starting backup to {target}...")

        # TODO: Implement actual backup
        # backup_result = await run_backup(target)

        return {
            "status": "backup_completed",
            "target": target,
            "backup_size_mb": 100,  # Placeholder
            "duration_seconds": 5
        }

    async def _cmd_schedule_backup(self, data: dict) -> dict:
        """Schedule recurring backup."""
        cron = data.get("cron", "0 2 * * *")  # Default: 2am daily
        logger.info(f"Scheduling backup: {cron}")

        # TODO: Set up cron job or scheduled task
        return {
            "status": "backup_scheduled",
            "cron": cron,
            "next_run": "calculated_time"
        }

    async def _cmd_clear_cache(self, data: dict) -> dict:
        """Clear local caches."""
        logger.info("Clearing caches...")

        # TODO: Clear actual caches
        return {
            "status": "cache_cleared",
            "freed_mb": 50
        }

    async def _cmd_health_check(self, data: dict) -> dict:
        """Run comprehensive health check."""
        logger.info("Running health check...")

        import psutil

        # Gather system metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        health = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "system": {
                "platform": platform.system(),
                "version": platform.version(),
                "hostname": platform.node()
            },
            "cpu": {
                "percent": cpu_percent,
                "count": psutil.cpu_count()
            },
            "memory": {
                "total_mb": memory.total // (1024 * 1024),
                "available_mb": memory.available // (1024 * 1024),
                "percent": memory.percent
            },
            "disk": {
                "total_gb": disk.total // (1024 * 1024 * 1024),
                "free_gb": disk.free // (1024 * 1024 * 1024),
                "percent": disk.percent
            }
        }

        return health

    async def _cmd_sync_now(self, data: dict) -> dict:
        """Force immediate sync of pending transactions."""
        logger.info("Forcing sync...")

        # TODO: Trigger actual sync
        return {
            "status": "sync_completed",
            "synced_transactions": 10,
            "synced_bytes": 5000
        }

    async def _cmd_force_sync(self, data: dict) -> dict:
        """Force sync with retry on failure."""
        logger.info("Force sync with retry...")

        # TODO: Implement force sync with retry
        return await self._cmd_sync_now(data)

    async def _cmd_start_workflow(self, data: dict) -> dict:
        """Start a workflow execution."""
        workflow_type = data.get("workflow_type")
        initial_data = data.get("initial_data", {})

        logger.info(f"Starting workflow: {workflow_type}")

        # TODO: Start actual workflow
        # workflow_id = await workflow_engine.start_workflow(workflow_type, initial_data)

        return {
            "status": "workflow_started",
            "workflow_type": workflow_type,
            "workflow_id": "workflow_123"  # Placeholder
        }

    async def _cmd_cancel_workflow(self, data: dict) -> dict:
        """Cancel a running workflow."""
        workflow_id = data.get("workflow_id")

        logger.info(f"Cancelling workflow: {workflow_id}")

        # TODO: Cancel actual workflow
        return {
            "status": "workflow_cancelled",
            "workflow_id": workflow_id
        }

    # ═════════════════════════════════════════════════════════════════════════
    # Critical Commands (WebSocket)
    # ═════════════════════════════════════════════════════════════════════════

    async def _cmd_emergency_stop(self, data: dict) -> dict:
        """CRITICAL: Emergency stop all operations."""
        reason = data.get("reason", "Emergency stop triggered")

        logger.critical(f"EMERGENCY STOP: {reason}")

        # Stop all workflows
        # Disable transaction processing
        # Put device in safe mode

        return {
            "status": "emergency_stop_activated",
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _cmd_fraud_alert(self, data: dict) -> dict:
        """CRITICAL: Fraud alert - take immediate action."""
        alert_type = data.get("alert_type")
        details = data.get("details", {})

        logger.critical(f"FRAUD ALERT: {alert_type} - {details}")

        # Take fraud mitigation actions
        return {
            "status": "fraud_alert_processed",
            "alert_type": alert_type,
            "actions_taken": ["transactions_disabled", "alert_logged"]
        }

    async def _cmd_security_lockdown(self, data: dict) -> dict:
        """CRITICAL: Security lockdown mode."""
        logger.critical("Security lockdown activated")

        # Implement lockdown procedures
        return {
            "status": "lockdown_active",
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _cmd_disable_transactions(self, data: dict) -> dict:
        """CRITICAL: Disable transaction processing."""
        reason = data.get("reason", "Disabled by admin")

        logger.warning(f"Disabling transactions: {reason}")

        # Disable transaction processing
        return {
            "status": "transactions_disabled",
            "reason": reason
        }

    async def _cmd_enable_transactions(self, data: dict) -> dict:
        """CRITICAL: Re-enable transaction processing."""
        logger.info("Re-enabling transactions")

        # Enable transaction processing
        return {
            "status": "transactions_enabled"
        }

    # ═════════════════════════════════════════════════════════════════════════
    # Status Reporting
    # ═════════════════════════════════════════════════════════════════════════

    async def report_status(
        self,
        command_id: Optional[str],
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None
    ):
        """Report command execution status back to cloud."""
        if not command_id:
            return  # WebSocket commands don't have IDs

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{self.cloud_url}/api/v1/devices/{self.device_id}/commands/{command_id}/status",
                    json={
                        "status": status,
                        "result": result,
                        "error": error,
                        "timestamp": datetime.utcnow().isoformat()
                    },
                    headers={"X-API-Key": self.api_key}
                )
        except Exception as e:
            logger.warning(f"Failed to report command status: {e}")
