"""
RufusEdgeAgent - Main agent class for fintech edge devices.

This is the primary interface for running Rufus on POS terminals,
ATMs, mobile readers, and other edge devices.
"""

import asyncio
import logging
import os
import uuid
from typing import Optional, Dict, Any
from datetime import datetime

from rufus.builder import WorkflowBuilder
from rufus.workflow import Workflow
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

from rufus_edge.models import (
    PaymentState,
    SAFTransaction,
    DeviceConfig,
    DeviceHealth,
    DeviceStatus,
    TransactionStatus,
)
from rufus_edge.sync_manager import SyncManager
from rufus_edge.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class RufusEdgeAgent:
    """
    Edge agent for fintech devices.

    This agent runs on POS terminals, ATMs, mobile readers, and kiosks.
    It provides:
    - Offline workflow execution with SQLite
    - Store-and-Forward for offline transactions
    - Config polling from cloud control plane
    - Automatic sync when connectivity is restored

    Example:
        agent = RufusEdgeAgent(
            device_id="pos-001",
            cloud_url="https://control.example.com",
            db_path="/var/lib/rufus/edge.db",
        )
        await agent.start()

        result = await agent.execute_workflow(
            "PaymentAuthorization",
            {"amount": "25.00", "card_token": "tok_xxx"}
        )
    """

    def __init__(
        self,
        device_id: str,
        cloud_url: str,
        api_key: Optional[str] = None,
        db_path: str = "rufus_edge.db",
        encryption_key: Optional[str] = None,
        config_poll_interval: int = 60,
        sync_interval: int = 30,
        heartbeat_interval: int = 60,
    ):
        """
        Initialize the edge agent.

        Args:
            device_id: Unique identifier for this device
            cloud_url: URL of the cloud control plane
            api_key: API key for authentication (or from env RUFUS_API_KEY)
            db_path: Path to SQLite database
            encryption_key: Key for encrypting sensitive data (or from env RUFUS_ENCRYPTION_KEY)
            config_poll_interval: Seconds between config polls
            sync_interval: Seconds between sync attempts
            heartbeat_interval: Seconds between heartbeats
        """
        self.device_id = device_id
        self.cloud_url = cloud_url.rstrip("/")
        self.api_key = api_key or os.getenv("RUFUS_API_KEY", "")
        self.db_path = db_path
        self.encryption_key = encryption_key or os.getenv("RUFUS_ENCRYPTION_KEY")
        self.config_poll_interval = config_poll_interval
        self.sync_interval = sync_interval
        self.heartbeat_interval = heartbeat_interval

        # Components (initialized in start())
        self.persistence: Optional[SQLitePersistenceProvider] = None
        self.executor: Optional[SyncExecutor] = None
        self.observer: Optional[LoggingObserver] = None
        self.workflow_builder: Optional[WorkflowBuilder] = None
        self.sync_manager: Optional[SyncManager] = None
        self.config_manager: Optional[ConfigManager] = None

        # State
        self._is_running = False
        self._is_online = False
        self._background_tasks: list[asyncio.Task] = []

    async def start(self):
        """Start the edge agent."""
        if self._is_running:
            logger.warning("Agent already running")
            return

        logger.info(f"Starting Rufus Edge Agent: {self.device_id}")

        # Initialize persistence
        self.persistence = SQLitePersistenceProvider(db_path=self.db_path)
        await self.persistence.initialize()

        # Initialize executor
        self.executor = SyncExecutor()

        # Initialize observer
        self.observer = LoggingObserver()

        # Initialize config manager
        self.config_manager = ConfigManager(
            config_url=self.cloud_url,
            device_id=self.device_id,
            api_key=self.api_key,
            poll_interval_seconds=self.config_poll_interval,
            persistence=self.persistence,
        )
        await self.config_manager.initialize()

        # Initialize sync manager
        self.sync_manager = SyncManager(
            persistence=self.persistence,
            sync_url=self.cloud_url,
            device_id=self.device_id,
            api_key=self.api_key,
        )
        await self.sync_manager.initialize()

        # Initialize workflow builder with empty registry (loaded from config)
        self.workflow_builder = WorkflowBuilder(
            config_dir="",  # Not used - workflows come from config
            workflow_registry={},
            persistence_provider=self.persistence,
            execution_provider=self.executor,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
            observer=self.observer,
        )

        # Register config change callback to reload workflows
        self.config_manager.on_config_change(self._on_config_change)

        # Check initial connectivity
        self._is_online = await self.sync_manager.check_connectivity()
        logger.info(f"Initial connectivity: {'online' if self._is_online else 'offline'}")

        # Start background tasks
        self._background_tasks.append(
            asyncio.create_task(self._sync_loop())
        )
        self._background_tasks.append(
            asyncio.create_task(self._heartbeat_loop())
        )

        # Start config polling
        await self.config_manager.start_polling()

        self._is_running = True
        logger.info(f"Rufus Edge Agent started: {self.device_id}")

    async def stop(self):
        """Stop the edge agent."""
        if not self._is_running:
            return

        logger.info(f"Stopping Rufus Edge Agent: {self.device_id}")

        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._background_tasks.clear()

        # Stop config polling
        if self.config_manager:
            await self.config_manager.stop_polling()
            await self.config_manager.close()

        # Close sync manager
        if self.sync_manager:
            await self.sync_manager.close()

        # Close persistence
        if self.persistence:
            await self.persistence.close()

        self._is_running = False
        logger.info(f"Rufus Edge Agent stopped: {self.device_id}")

    async def execute_workflow(
        self,
        workflow_type: str,
        data: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute a workflow locally.

        Args:
            workflow_type: Type of workflow to execute
            data: Initial workflow data
            timeout: Optional timeout in seconds

        Returns:
            Workflow result dict
        """
        if not self._is_running:
            raise RuntimeError("Agent not started")

        # Get workflow config from config manager
        workflow_config = self.config_manager.get_workflow_config(workflow_type)
        if not workflow_config:
            raise ValueError(f"Unknown workflow type: {workflow_type}")

        # Generate idempotency key if not provided
        if "idempotency_key" not in data:
            data["idempotency_key"] = f"{self.device_id}:{uuid.uuid4().hex}"

        # Create workflow
        workflow = await self.workflow_builder.create_workflow(
            workflow_type=workflow_type,
            initial_data=data,
            owner_id=self.device_id,
        )

        # Execute to completion
        try:
            while workflow.status == "ACTIVE":
                result, next_step = await workflow.next_step()

                if workflow.status in ["COMPLETED", "FAILED", "WAITING_HUMAN"]:
                    break

            return {
                "workflow_id": workflow.id,
                "status": workflow.status,
                "state": workflow.state.model_dump() if hasattr(workflow.state, 'model_dump') else workflow.state,
                "result": result if 'result' in dir() else {},
            }

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            return {
                "workflow_id": workflow.id,
                "status": "FAILED",
                "error": str(e),
            }

    async def process_payment(
        self,
        amount: float,
        card_token: str,
        merchant_id: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Process a payment transaction.

        This is a convenience method that handles offline fallback
        and Store-and-Forward automatically.

        Args:
            amount: Transaction amount
            card_token: Tokenized card reference
            merchant_id: Merchant identifier
            **kwargs: Additional transaction data

        Returns:
            Payment result dict
        """
        transaction_id = f"txn_{uuid.uuid4().hex[:12]}"
        idempotency_key = f"{merchant_id}:{transaction_id}"

        # Check connectivity
        is_online = await self.sync_manager.check_connectivity()

        if is_online:
            # Online flow - execute payment workflow
            result = await self.execute_workflow(
                workflow_type="PaymentAuthorization",
                data={
                    "transaction_id": transaction_id,
                    "idempotency_key": idempotency_key,
                    "amount": amount,
                    "card_token": card_token,
                    "merchant_id": merchant_id,
                    "terminal_id": self.device_id,
                    "is_online": True,
                    **kwargs,
                }
            )
            return result

        else:
            # Offline flow - check floor limit and queue for sync
            floor_limit = self.config_manager.get_floor_limit()

            if amount > floor_limit:
                return {
                    "transaction_id": transaction_id,
                    "status": "DECLINED",
                    "reason": f"Amount ${amount} exceeds offline floor limit ${floor_limit}",
                    "is_offline": True,
                }

            # Create SAF transaction
            saf_txn = SAFTransaction(
                transaction_id=transaction_id,
                idempotency_key=idempotency_key,
                device_id=self.device_id,
                merchant_id=merchant_id,
                amount=amount,
                currency=kwargs.get("currency", "USD"),
                card_token=card_token,
                card_last_four=kwargs.get("card_last_four", "****"),
                status=TransactionStatus.APPROVED_OFFLINE,
                offline_approved_at=datetime.utcnow(),
            )

            # Queue for sync
            await self.sync_manager.queue_for_sync(saf_txn)

            return {
                "transaction_id": transaction_id,
                "status": "APPROVED_OFFLINE",
                "is_offline": True,
                "requires_sync": True,
                "floor_limit": floor_limit,
            }

    def get_health(self) -> DeviceHealth:
        """Get current device health status."""
        return DeviceHealth(
            device_id=self.device_id,
            status=DeviceStatus.ONLINE if self._is_online else DeviceStatus.OFFLINE,
            is_online=self._is_online,
            pending_sync=0,  # TODO: Get from sync manager
            last_sync_at=self.sync_manager._last_sync_at if self.sync_manager else None,
            last_config_pull_at=self.config_manager._last_poll_at if self.config_manager else None,
        )

    def _on_config_change(self, config: DeviceConfig):
        """Handle config changes."""
        logger.info(f"Config changed to version {config.version}")

        # Update workflow registry
        if self.workflow_builder and config.workflows:
            self.workflow_builder.workflow_registry = config.workflows
            logger.info(f"Updated workflow registry with {len(config.workflows)} workflows")

    async def _sync_loop(self):
        """Background sync loop."""
        while True:
            try:
                await asyncio.sleep(self.sync_interval)

                # Check connectivity
                self._is_online = await self.sync_manager.check_connectivity()

                if self._is_online:
                    # Attempt sync
                    pending = await self.sync_manager.get_pending_count()
                    if pending > 0:
                        logger.info(f"Syncing {pending} pending transactions...")
                        report = await self.sync_manager.sync_all_pending()
                        logger.info(
                            f"Sync complete: {report.synced_count} synced, "
                            f"{report.failed_count} failed"
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sync loop error: {e}")

    async def _heartbeat_loop(self):
        """Background heartbeat loop."""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                # TODO: Send heartbeat to cloud
                # await self._send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
