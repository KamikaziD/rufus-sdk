"""
Ruvon Edge SDK - Python-native workflow engine for fintech edge devices.

This package provides:
- RuvonEdgeAgent: Main agent class for POS terminals, ATMs, mobile readers
- SyncManager: Store-and-Forward transaction sync
- ConfigManager: ETag-based config polling from cloud
- Encrypted SQLite persistence for offline operation

Example usage:
    from ruvon_edge import RuvonEdgeAgent

    agent = RuvonEdgeAgent(
        device_id="pos-terminal-001",
        cloud_url="https://control.example.com",
        db_path="/var/lib/ruvon/edge.db",
        encryption_key=os.getenv("RUVON_ENCRYPTION_KEY"),
    )

    await agent.start()

    # Process a payment (works offline)
    result = await agent.execute_workflow(
        workflow_type="PaymentAuthorization",
        data={"amount": "25.00", "card_token": "tok_xxx"}
    )
"""

from ruvon_edge.agent import RuvonEdgeAgent
from ruvon_edge.sync_manager import SyncManager
from ruvon_edge.config_manager import ConfigManager, UpdateInstruction
try:
    from ruvon_edge.inference_executor import (
        InferenceExecutor,
        get_inference_executor,
        initialize_inference_executor,
    )
except ImportError:
    InferenceExecutor = None  # type: ignore[assignment,misc]
    get_inference_executor = None  # type: ignore[assignment]
    initialize_inference_executor = None  # type: ignore[assignment]
from ruvon_edge.models import (
    PaymentState,
    SAFTransaction,
    DeviceConfig,
    SyncStatus,
)

__version__ = "0.1.2"

__all__ = [
    "RuvonEdgeAgent",
    "SyncManager",
    "ConfigManager",
    "UpdateInstruction",
    "InferenceExecutor",
    "get_inference_executor",
    "initialize_inference_executor",
    "PaymentState",
    "SAFTransaction",
    "DeviceConfig",
    "SyncStatus",
]
