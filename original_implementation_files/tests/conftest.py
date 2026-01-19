from src.confucius.workflow import Workflow as _Workflow
import pytest
import sys
from pathlib import Path
from dotenv import load_dotenv
import os

# Ensure project's src/ is on sys.path so `import confucius` works
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Load environment variables from project .env for tests run inside containers
env_path = ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Set a fallback DATABASE_URL for local unit tests if not provided by environment
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://confucius:secretpassword@postgres:5432/confucius"
)

# --------------------------------------------------------------------
# Test-time in-memory persistence shim
# --------------------------------------------------------------------
# For fast unit tests (non-integration) we provide an autouse fixture that
# monkeypatches persistence functions to use an in-memory store. Integration
# tests can opt-in by setting environment variable RUN_INTEGRATION=true.
#
# This prevents pytest collection / unit test runs from attempting to
# connect to Postgres or Redis on import-time.


@pytest.fixture(scope="session", autouse=True)
def _mock_persistence(): # Removed monkeypatch argument
    """Autouse fixture that replaces persistence with an in-memory store unless
    RUN_INTEGRATION env var is set to true."""
    run_integration = os.getenv(
        "RUN_INTEGRATION", "false").lower() in ("1", "true", "yes")
    if run_integration:
        # Leave real persistence intact for integration runs
        yield # Must yield even if not patching, for autouse fixtures
        return

    _store = {}

    class MockWorkflowStore:
        def save(self, workflow_id: str, workflow_instance):
            mem_save_workflow_state(workflow_id, workflow_instance) # Delegate to our in-memory save
            return None # Mimic RedisStore's return for simplicity in test mock

        def load(self, workflow_id: str):
            return mem_load_workflow_state(workflow_id) # Delegate to our in-memory load

    def mem_save_workflow_state(workflow_id: str, workflow_instance, store=None):
        _store[workflow_id] = workflow_instance.to_dict()

    def mem_load_workflow_state(workflow_id: str, store=None):
        data = _store.get(workflow_id)
        if not data:
            return None
        # Dynamically get Workflow class to avoid circular import at file level
        _Workflow_class = sys.modules['src.confucius.workflow'].Workflow
        # Pass a store when creating new Workflow object, it can be our mock store
        return _Workflow_class.from_dict(data, store=MockWorkflowStore()) 

    # Store original functions for restoration
    import src.confucius.persistence as persistence_module
    original_save_workflow_state = persistence_module.save_workflow_state
    original_load_workflow_state = persistence_module.load_workflow_state
    original_get_workflow_store = persistence_module.get_workflow_store 

    mock_store_instance = MockWorkflowStore()

    # Apply patches
    persistence_module.save_workflow_state = mem_save_workflow_state
    persistence_module.load_workflow_state = mem_load_workflow_state
    persistence_module.get_workflow_store = lambda: mock_store_instance # Make get_workflow_store return our mock store

    yield # Tests run here

    # Restore original functions after session
    persistence_module.save_workflow_state = original_save_workflow_state
    persistence_module.load_workflow_state = original_load_workflow_state
    persistence_module.get_workflow_store = original_get_workflow_store
    _store.clear()
