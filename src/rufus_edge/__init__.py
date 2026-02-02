"""
Rufus Edge SDK - Python-native workflow engine for fintech edge devices.

This package provides:
- RufusEdgeAgent: Main agent class for POS terminals, ATMs, mobile readers
- SyncManager: Store-and-Forward transaction sync
- ConfigManager: ETag-based config polling from cloud
- Encrypted SQLite persistence for offline operation

Example usage:
    from rufus_edge import RufusEdgeAgent

    agent = RufusEdgeAgent(
        device_id="pos-terminal-001",
        cloud_url="https://control.example.com",
        db_path="/var/lib/rufus/edge.db",
        encryption_key=os.getenv("RUFUS_ENCRYPTION_KEY"),
    )

    await agent.start()

    # Process a payment (works offline)
    result = await agent.execute_workflow(
        workflow_type="PaymentAuthorization",
        data={"amount": "25.00", "card_token": "tok_xxx"}
    )
"""

from rufus_edge.agent import RufusEdgeAgent
from rufus_edge.sync_manager import SyncManager
from rufus_edge.config_manager import ConfigManager
from rufus_edge.models import (
    PaymentState,
    SAFTransaction,
    DeviceConfig,
    SyncStatus,
)

__version__ = "0.1.0"

__all__ = [
    "RufusEdgeAgent",
    "SyncManager",
    "ConfigManager",
    "PaymentState",
    "SAFTransaction",
    "DeviceConfig",
    "SyncStatus",
]
