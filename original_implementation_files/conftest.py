from pathlib import Path
import sys
import os
from pathlib import Path
import pytest

# Ensure project's src/ is on sys.path so `import confucius` works
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))



# Decide whether this pytest run is intended as an integration run.
run_integration = os.getenv(
    "RUN_INTEGRATION", "false").lower() in ("1", "true", "yes")



# --------------------------------------------------------------------
# Test-time in-memory persistence shim (applies to root-level tests)
# --------------------------------------------------------------------
# For fast unit tests (non-integration) we provide an autouse fixture that
# monkeypatches persistence functions to use an in-memory store. Integration
# tests can opt-in by setting environment variable RUN_INTEGRATION=true.
#
# This prevents pytest collection / unit test runs from attempting to
# connect to Postgres or Redis on import-time for top-level tests.
#

@pytest.fixture(autouse=True)
def _mock_persistence(monkeypatch):
    """Autouse fixture that replaces persistence with an in-memory store unless
    RUN_INTEGRATION env var is set to true.

    Also ensures TESTING mode and WORKFLOW_STORAGE=redis for non-integration runs
    so Celery/async paths run synchronously and Postgres initialization is bypassed.
    """
    run_integration = os.getenv(
        "RUN_INTEGRATION", "false").lower() in ("1", "true", "yes")
    if run_integration:
        # Leave real persistence intact for integration runs
        return

    # Only set defaults if they are not already provided by the environment
    os.environ.setdefault("WORKFLOW_STORAGE", "redis")
    os.environ.setdefault("TESTING", "true")

    _store = {}

    def mem_save_workflow_state(workflow_id: str, workflow_instance):
        # Accept Workflow instance or dict
        try:
            if hasattr(workflow_instance, "to_dict"):
                _store[workflow_id] = workflow_instance.to_dict()
            else:
                _store[workflow_id] = workflow_instance
        except Exception:
            _store[workflow_id] = workflow_instance

    def mem_load_workflow_state(workflow_id: str):
        data = _store.get(workflow_id)
        if not data:
            return None
        # If already a dict-like, reconstruct Workflow via from_dict if available
        try:
            from confucius.workflow import Workflow as _Workflow
            return _Workflow.from_dict(data)
        except Exception:
            return data

    # Patch persistence functions used across tests
    # Use the package import path so both tests importing via src/ and top-level
    # modules are patched.
    try:
        monkeypatch.setattr("confucius.persistence.save_workflow_state",
                            mem_save_workflow_state, raising=False)
        monkeypatch.setattr("confucius.persistence.load_workflow_state",
                            mem_load_workflow_state, raising=False)
        monkeypatch.setattr(
            "confucius.persistence.get_storage_backend", lambda: "redis", raising=False)
    except Exception:
        # Best-effort: some tests import modules differently; try alternate paths.
        try:
            monkeypatch.setattr("src.confucius.persistence.save_workflow_state",
                                mem_save_workflow_state, raising=False)
            monkeypatch.setattr("src.confucius.persistence.load_workflow_state",
                                mem_load_workflow_state, raising=False)
            monkeypatch.setattr(
                "src.confucius.persistence.get_storage_backend", lambda: "redis", raising=False)
        except Exception:
            pass

    yield

    _store.clear()

